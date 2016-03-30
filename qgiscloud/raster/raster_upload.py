# This is a simple utility used to dump GDAL dataset into HEX WKB stream.
# It's considered as a prototype of raster2pgsql tool planned to develop
# in future.
# For more details about raster2pgsql tool, see Specification page:
# http://trac.osgeo.org/postgis/wiki/WKTRaster
#
# The script requires Python bindings for GDAL.
# Available at http://trac.osgeo.org/gdal/wiki/GdalOgrInPython
#
################################################################################
# Copyright (C) 2009-2010 Mateusz Loskot <mateusz@loskot.net>
# Copyright (C) 2009-2011 Pierre Racine <pierre.racine@sbf.ulaval.ca>
# Copyright (C) 2009-2010 Jorge Arevalo <jorge.arevalo@deimos-space.com>
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
################################################################################
#
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from qgis.core import *
from osgeo import gdal
from osgeo import osr
import osgeo.gdalconst as gdalc
from optparse import OptionParser, OptionGroup
import binascii
import glob
import math
import numpy
import os
import sys

################################################################################
# CONSTANTS - DO NOT CHANGE

# Endianness enumeration
NDR = 1 # Little-endian
XDR = 0 # Big-endian

# Default version of WKTRaster protocol.
# WARNING: Currently, this is the only valid value
# and option -w, --raster-version is ignored, if specified.
g_rt_version = 0

# Default format of binary output is little-endian (NDR)
# WARNING: Currently, big-endian (XDR) output is not supported
# and option -e, --endian is ignored, if specified.
g_rt_endian = NDR

# Default name of column, overriden with -f, --field option.
g_rt_column = 'rast'

g_rt_catalog = ''
g_rt_schema = 'public'

################################################################################
# UTILITIES
VERBOSE = False
SUMMARY = []

class RasterUpload():
    def __init__(self,  conn,  cursor,  raster):
    
        (opts, args) = self.parse_options()
        
        opts.version = g_rt_version
        opts.endian = NDR
        opts.srid = 4326
#        opts.create_raster_overviews_table = 1
        opts.column = 'wkb_raster'
        opts.create_table = 1
        opts.drop_table = 1
        opts.overview_level = 1
         
        self.upload_string = 'BEGIN;\n'
        
        # If overviews requested, CREATE TABLE raster_overviews
        if opts.create_raster_overviews_table:
            sql = self.make_sql_create_raster_overviews(opts)
            self.upload_string += sql

        i = 0

        gt = None
        for infile in raster:
            opts.table = os.path.splitext(os.path.basename(infile))[0]
        # Base raster schema
            if opts.overview_level == 1:
                # DROP TABLE
                if opts.drop_table:
                    sql = self.make_sql_drop_table(opts.table)
                    self.upload_string += sql            
                    
            # CREATE TABLE
            if opts.create_table and opts.overview_level == 1:
                sql = self.make_sql_create_table(opts, os.path.splitext(os.path.basename(infile))[0] ,  opts.column)
                self.upload_string += sql            
                
                # Write raster data to WKB and send it to opts.output
                gt = self.wkblify_raster(opts,  infile.replace( '\\', '/') , i, gt)
                i += 1
    
        # INDEX
        sql = self.make_sql_create_gist(opts.table, opts.column)
        self.upload_string += sql
        
        # COMMIT
        self.upload_string += 'END;\n'
#        print self.upload_string
        cursor.execute(self.upload_string)
        conn.commit
        
        

    
    ################################################################################
    
    def is_nan(self,  x):
        if sys.hexversion < 0x02060000:
            return str(float(x)).lower() == 'nan'
        else:
            return math.isnan(x)
    
    def parse_options(self):
        """Collects, parses and validates command line arguments."""
    
        prs = OptionParser(version="%prog $Revision$")
    
        # Mandatory parameters
        grp0 = OptionGroup(prs, "Source and destination",
               "*** Mandatory parameters always required ***")
        grp0.add_option("-r", "--raster", dest="raster", action="append", default=None,
             help="append raster to list of input files, at least one raster "
                        "file required. You may use wildcards (?,*) for specifying multiple files.")
        grp0.add_option("-t", "--table", dest="table", action="store", default=None,
             help="raster destination in form of [<schema>.]<table> or base raster table for overview level>1, required")
        prs.add_option_group(grp0);
    
        # Optional parameters - raster manipulation
        grp_r = OptionGroup(prs, "Raster processing",
                "Optional parameters used to manipulate input raster dataset")
        grp_r.add_option("-s", "--srid", dest="srid", action="store", type="int", default=-1, 
              help="assign output raster with specified SRID")
        grp_r.add_option("-b", "--band", dest="band", action="store", type="int", default=None,
                         help="specify number of the band to be extracted from raster file")
        grp_r.add_option("-k", "--block-size", dest="block_size", action="store", default=None,
                         help="cut raster(s) into tiles to be inserted one by table row."
                         "BLOCK_SIZE is expressed as WIDTHxHEIGHT. Incomplete tiles are completed with nodata values")
        grp_r.add_option("-R", "--register", dest="register", action="store_true", default=False, 
                         help="register the raster as a filesystem (out-db) raster")
        grp_r.add_option("-l", "--overview-level", dest="overview_level", action="store", type="int", default=1,
                         help='create overview tables named as o_<LEVEL>_<RASTER_TABLE> and '
                         'populate with GDAL-provided overviews (regular blocking only)')
        prs.add_option_group(grp_r);
    
        # Optional parameters - database/table manipulation
        grp_t = OptionGroup(prs, 'Database processing',
                            'Optional parameters used to manipulate database objects')
        grp_t.add_option('-c', '--create', dest='create_table', action='store_true', default=False, 
                         help='create new table and populate it with raster(s), this is the default mode')
        grp_t.add_option('-a', '--append', dest='append_table', action='store_true', default=False, 
                         help='append raster(s) to an existing table')
        grp_t.add_option("-d", "--drop", dest="drop_table", action="store_true", default=False, 
                         help="drop table, create new one and populate it with raster(s)")
        grp_t.add_option("-f", "--field", dest="column", action="store", default=g_rt_column, 
                         help="specify name of destination raster column, default is 'rast'")
        grp_t.add_option("-F", "--filename", dest="filename", action="store_true", default=False, 
                         help="add a column with the name of the file")
        grp_t.add_option("-I", "--index", dest="index", action="store_true", default=False, 
                         help="create a GiST index on the raster column")
        grp_t.add_option("-M", "--vacuum", dest="vacuum", action="store_true", default=False, 
                         help="issue VACUUM command against all generated tables")
        grp_t.add_option('-V', '--create-raster-overviews', dest='create_raster_overviews_table',
                         action='store_true', default=False,
                         help='create RASTER_OVERVIEWS table used to store overviews metadata')
        prs.add_option_group(grp_t);
    
        # Other optional parameters
        grp_u = OptionGroup(prs, "Miscellaneous", "Other optional parameters")
        grp_u.add_option("-e", "--endian", dest="endian", action="store", type="int", default=g_rt_endian, 
                         help="control endianness of generated binary output of raster; "
                         "specify 0 for XDR and 1 for NDR (default); "
                         "only NDR output is supported now")
        grp_u.add_option("-w", "--raster-version", dest="version",
                         action="store", type="int", default=g_rt_version, 
                         help="specify version of raster protocol, default is 0; "
                         "only value of zero is supported now")
        grp_u.add_option("-o", "--output", dest="output", action="store", default=sys.stdout,
                         help="specify output file, otherwise send to stdout")
        grp_u.add_option("-v", "--verbose", dest="verbose", action="store_true", default=False,
                         help="verbose mode. Useful for debugging")
        prs.add_option_group(grp_u);
        
        (opts, args) = prs.parse_args()
        return opts,  args

        
        
#        # Validate options
#        if opts.create_table and opts.drop_table and opts.append_table:
#            prs.error("options -c, -a and -d are mutually exclusive")
#        if opts.create_table and opts.drop_table:
#            prs.error("options -c and -d are mutually exclusive")
#        if opts.create_table and opts.append_table:
#            prs.error("options -c and -a are mutually exclusive")
#        if opts.append_table and opts.drop_table:
#            prs.error("options -a and -d are mutually exclusive")
#        if (not opts.create_table and not opts.drop_table and not opts.append_table) or opts.drop_table:
#            opts.create_table = True
#    
#        if opts.raster is None:
#            prs.error("use option -r to specify at least one input raster. Wildcards (?,*) are accepted.")
#    
#        if opts.block_size is not None and len(opts.raster) != 1:
#            prs.error("regular blocking supports single-raster input only")
#    
#        if opts.block_size is not None:
#            if len(opts.block_size.split('x')) != 2 and len(opts.block_size.split('X')) != 2:
#                prs.error("invalid format of block size, expected WIDTHxHEIGHT")
#    
#        if opts.overview_level > 1 and opts.block_size is None:
#            prs.error("regular blocking mode required to enable overviews support (level > 1)")
#    
#        if opts.create_raster_overviews_table and opts.overview_level <= 1:
#            prs.error('create table for RASTER_OVERVIEWS available only if overviews import requested')
#    
#        # XXX: Now, if --band=Nth, then only Nth band of all specified rasters is dumped/imported
#        #      This behavior can be changed to support only single-raster input if --band option used.
#        #if opts.band is not None and len(opts.raster) > 1:
#        #    prs.error("option -b requires single input raster only, specify -r option only once")
#    
#        if opts.table is None:
#            prs.error("use option -t to specify raster destination table")
#        if len(opts.table.split('.')) > 2:
#            prs.error("invalid format of table name specified with option -t, expected [<schema>.]table")
#    
#        if opts.output is None:
#            prs.error("failed to initialise output file, try to use option -o explicitly")
#    
#        if opts.version is not None:
#            if opts.version != g_rt_version:
#                prs.error("invalid version of WKT Raster protocol specified, only version 0 is supported")
#        else:
#            prs.error("use option -w to specify version of WKT Raster protocol")
#    
#        if opts.endian is not None:
#            if opts.endian != NDR and opts.endian != XDR:
#                prs.error("invalid endianness value, valid ones are 0 for NDR or 1 for XDR")
#        else:
#            prs.error("use option -e to specify endianness of binary output")
#    
#        QMessageBox.information(None,  '',  str(opts))
#        return (opts, args)
    
    
    def logit(self,  msg):
        """If verbose mode requested, sends extra progress information to stderr"""
        if VERBOSE is True:
            pass
#            sys.stderr.write(msg)        
    
    
    def gdt2pt(self,  gdt):
        """Translate GDAL data type to WKT Raster pixel type."""
        pixtypes = {
            gdalc.GDT_Byte    : { 'name': 'PT_8BUI',  'id':  4 },
            gdalc.GDT_Int16   : { 'name': 'PT_16BSI', 'id':  5 },
            gdalc.GDT_UInt16  : { 'name': 'PT_16BUI', 'id':  6 },
            gdalc.GDT_Int32   : { 'name': 'PT_32BSI', 'id':  7 },
            gdalc.GDT_UInt32  : { 'name': 'PT_32BUI', 'id':  8 },
            gdalc.GDT_Float32 : { 'name': 'PT_32BF',  'id': 10 },
            gdalc.GDT_Float64 : { 'name': 'PT_64BF',  'id': 11 }
            }
        
        # XXX: Uncomment these logs to debug types translation
        #logit('MSG: Input GDAL pixel type: %s (%d)\n' % (gdal.GetDataTypeName(gdt), gdt))
        #logit('MSG: Output WKTRaster pixel type: %(name)s (%(id)d)\n' % (pixtypes.get(gdt, 13)))
    
        return pixtypes.get(gdt, 13)
    
    def pt2numpy(self,  pt):
        """Translate GDAL data type to NumPy data type"""
        ptnumpy = {
            gdalc.GDT_Byte   : numpy.uint8,
            gdalc.GDT_Int16  : numpy.int16,
            gdalc.GDT_UInt16  : numpy.uint16,
            gdalc.GDT_Int32  : numpy.int32,
            gdalc.GDT_UInt32 : numpy.uint32,
            gdalc.GDT_Float32: numpy.float32,
            gdalc.GDT_Float64: numpy.float64
            }
        return ptnumpy.get(pt, numpy.uint8)
    
    def pt2fmt(self,  pt):
        """Returns binary data type specifier for given pixel type."""
        fmttypes = {
            4: 'B', # PT_8BUI
            5: 'h', # PT_16BSI
            6: 'H', # PT_16BUI
            7: 'i', # PT_32BSI
            8: 'I', # PT_32BUI
            10: 'f', # PT_32BF
            11: 'd'  # PT_64BF
            }
        return fmttypes.get(pt, 'x')
    
    
    def fmt2printfmt(self,  fmt):
        """Returns printf-like formatter for given binary data type sepecifier."""
        fmttypes = {
            'B': '%d', # PT_8BUI
            'h': '%d', # PT_16BSI
            'H': '%d', # PT_16BUI
            'i': '%d', # PT_32BSI
            'I': '%d', # PT_32BUI
            'f': '%.15f', # PT_32BF
            'd': '%.15f', # PT_64BF
            's': '%s'
            }
        return fmttypes.get(fmt, 'f')
    
    def parse_block_size(self,  options):
        assert options is not None
        assert options.block_size is not None
    
        wh = options.block_size.split('x')
        if len(wh) != 2:
            wh = options.block_size.split('X')
    
        assert len(wh) == 2, "invalid format of specified block size"
        return ( int(wh[0]), int(wh[1]) )
        
    ################################################################################
    # SQL OPERATIONS
    
    def quote_sql_value(self,  value):
        assert value is not None, "None value given"
    
        if len(value) > 0 and value[0] != "'" and value[:-1] != "'":
            sql = "'" + str(value) + "'"
        else:
            sql = value
        return sql
    
    def quote_sql_name(self,  name):
        assert name is not None, "None name given"
    
        if name[0] != "\"" and name[:-1] != "\"":
            sql = "\"" + str(name) + "\""
        else:
            sql = name
        return sql
    
    def make_sql_value_array(self,  values):
        sql = "ARRAY["
        for v in values:
            if type(v) == str:
                sql += self.quote_sql_value(v) + ","
            else:
                sql += str(v) + ','
        sql = sql[:-1] # Trim comma
        sql += "]"
        return sql
    
    def make_sql_schema_table_names(self,  schema_table):
        st = schema_table.split('.')
        if len(st) == 1:
            # TODO: Should we warn user that public is used implicitly?
            st.insert(0, "public")
        assert len(st) == 2, "Invalid format of table name, expected [<schema>.]table"
        return (st[0], st[1])
    
    def make_sql_full_table_name(self,  schema_table):
        st = self.make_sql_schema_table_names(schema_table)
        table = "\"%s\".\"%s\"" % (st[0], st[1])
        return table
    
    def make_sql_table_name(self,  schema_table):
        st = schema_table.split('.')
        assert len(st) == 1 or len(st) == 2, "Invalid format of table name, expected [<schema>.]table"
        if len(st) == 2:
            return st[1]
        return st[0]
    
    def make_sql_drop_table(self,  table):
        sql = "DROP TABLE IF EXISTS %s CASCADE;\n" \
              % self.make_sql_full_table_name(table)
        self.logit("SQL: %s" % sql)
        return sql
    
    def make_sql_drop_raster_table(self,  table):
        st = self.make_sql_schema_table_names(table)
    
        if len(st[0]) == 0:
            target = "'', '%s'" % st[1]
        else:
            target = "'%s', '%s'" % (st[0], st[1])
        sql = "SELECT DropRasterTable(%s);\n" % target
        self.logit("SQL: %s" % sql)
        return sql
    
    
    def make_sql_create_table(self,  options, table,  column,  is_overview = False):
    
        sql = "CREATE TABLE %s (rid serial PRIMARY KEY, %s RASTER);\n" \
              % (self.make_sql_full_table_name(table), self.quote_sql_name(column))
        return sql
    
    
    def make_sql_create_gist(self,  table, column):
        gist_table = self.make_sql_table_name(table)
        target_table = self.make_sql_full_table_name(table)

        sql = "CREATE INDEX \"%s_%s_gist_idx\" ON %s USING GIST (st_convexhull(%s));\n" % \
              (gist_table, column, target_table, column)

        return sql;
    
    
    def make_sql_addrastercolumn(self,  options, pixeltypes, nodata, pixelsize, blocksize, extent):
        assert len(pixeltypes) > 0, "No pixel types given"
        ts = self.make_sql_schema_table_names(options.table)
        pt = self.make_sql_value_array(pixeltypes)
    
        nd = 'null'
        if nodata is not None and len(nodata) > 0:
            nd = self.make_sql_value_array(nodata)
    
        odb = 'false'
        if options.register:
            odb = 'true'
    
        rb = 'false'
        extgeom = 'null'
        bs = ( 'null', 'null' )
        # Check if regular blocking mode requested
        if options.block_size is not None:
            assert pixelsize is not None, "Pixel size is none, but regular blocking requested"
            assert blocksize is not None, "Block size is none, but regular blocking requested"
            assert extent is not None, "Extent is none, but regular blocking requested"
            assert len(pixelsize) == 2, "Invalid pixel size, two values expected"
            assert len(blocksize) == 2, "Invalid block size, two values expected"
            assert len(extent) == 4, "Invalid extent, four coordinates expected"
            assert len(extent[0]) == len(extent[3]) == 2, "Invalid extent, pair of X and Y pair expected"
            rb = 'true'
            bs = ( blocksize[0], blocksize[1] )
            extgeom = "ST_Envelope(ST_SetSRID('POLYGON((%.15f %.15f,%.15f %.15f,%.15f %.15f,%.15f %.15f,%.15f %.15f))'::geometry, %d))" % \
                      (extent[0][0], extent[0][1], extent[1][0], extent[1][1],
                       extent[2][0], extent[2][1], extent[3][0], extent[3][1],
                       extent[0][0], extent[0][1], options.srid)
    
        sql = "SELECT AddRasterColumn('%s','%s','%s',%d, %s, %s, %s, %s, %.15f, %.15f, %s, %s, %s);\n" % \
               (ts[0], ts[1], options.column, options.srid, pt, odb, rb, nd,
                pixelsize[0], pixelsize[1], bs[0], bs[1], extgeom)
    
        self.logit("SQL: %s" % sql)
        return sql
    
    def make_sql_insert_raster(self,  table, rast, hexwkb):
        sql = "INSERT INTO %s ( %s ) VALUES ( (\'%s\')::raster );\n" \
              % (self.make_sql_full_table_name(table), rast, hexwkb)
    
        return sql
    
    def make_sql_create_raster_overviews(self,  options):
        schema = self.make_sql_schema_table_names(options.table)[0]
        table = self.make_sql_full_table_name(schema + '.raster_overviews')
        sql = 'CREATE TABLE ' + table + ' ( ' \
              'o_table_catalog character varying(256) NOT NULL, ' \
              'o_table_schema character varying(256) NOT NULL, ' \
              'o_table_name character varying(256) NOT NULL, ' \
              'o_column character varying(256) NOT NULL, ' \
              'r_table_catalog character varying(256) NOT NULL, ' \
              'r_table_schema character varying(256) NOT NULL, ' \
              'r_table_name character varying(256) NOT NULL, ' \
              'r_column character varying(256) NOT NULL, ' \
              'out_db boolean NOT NULL, ' \
              'overview_factor integer NOT NULL, ' \
              'CONSTRAINT raster_overviews_pk ' \
              'PRIMARY KEY (o_table_catalog, o_table_schema, o_table_name, o_column, overview_factor));\n'
        
        return sql
    
    
    def make_sql_register_overview(self,  options, ov_table, ov_factor):
        assert len(ov_table) > 0
        assert ov_factor > 0
        
        catalog = self.quote_sql_value('')
        schema = self.make_sql_schema_table_names(options.table)[0]
        r_table = self.make_sql_table_name(options.table)
    
        sql = "INSERT INTO public.raster_overviews( " \
              "o_table_catalog, o_table_schema, o_table_name, o_column, " \
              "r_table_catalog, r_table_schema, r_table_name, r_column, out_db, overview_factor) " \
              "VALUES ('%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', FALSE, %d);\n" % \
              (catalog, schema, ov_table, options.column, catalog, schema, r_table, options.column, ov_factor)
        
        return sql
    
    def make_sql_vacuum(self,  table):
        sql = 'VACUUM ANALYZE ' + self.make_sql_full_table_name(table) + ';\n'
        return sql
    
    ################################################################################
    # RASTER OPERATIONS
    
    def calculate_overviews(self,  ds, band_from = None, band_to = None):
        assert ds is not None
    
        if band_from is None:
            band_from = 0
        if band_to is None:
            band_to = ds.RasterCount
    
        assert band_to <= ds.RasterCount,'Failed checking band_to=%d <= RasterCount=%d' % (band_to,ds.RasterCount)
        assert band_from <= band_to
    
        nov = 0
        for i in range(band_from, band_to + 1):
            n = ds.GetRasterBand(i).GetOverviewCount()
            if 0 == nov:
                nov = n
            assert n == nov, 'Number of raster overviews is not the same for all bands'
    
        return nov
    
    def calculate_overview_factor(self,  ds, overview):
        assert ds is not None
    
    
        # Assume all bands have same layout of overviews        
        band = ds.GetRasterBand(1)
        assert band is not None
        assert overview < band.GetOverviewCount()
        
        ov_band = band.GetOverview(overview)
        assert ov_band is not None
        
        ovf = int(0.5 + ds.RasterXSize / float(ov_band.XSize))
        self.logit('MSG: Overview factor = %d\n' % ovf)
    
        return ovf
            
        
    def collect_pixel_types(self,  ds, band_from, band_to):
        """Collect pixel types of bands in requested range.
           Use names of pixel types in format as returned
           by rt_core function rt_pixtype_name()"""
    
        pt =[]
        for i in range(band_from, band_to):
            band = ds.GetRasterBand(i)
            pixel_type = self.gdt2pt(band.DataType)['name'][3:]
            pt.append(pixel_type)
        
        return pt
    
    def collect_nodata_values(self,  ds, band_from, band_to):
        """Collect nodata values of bands in requested range"""
    
        nd = []
        for i in range(band_from, band_to):
            band = ds.GetRasterBand(i)
            nodata = band.GetNoDataValue()
            if nodata is not None and not is_nan(nodata):
                nd.append(nodata)
    
        return nd
    
    def calculate_block_size(self,  ds, band_from, band_to):
        """Size of natural block reported by GDAL for bands of given dataset"""
    
        block_dims = None
        for i in range(band_from, band_to):
            band = ds.GetRasterBand(i)
            assert band is not None, "Cannot access raster band %d" % i
            dims = band.GetBlockSize()
    
            # Assume bands with common block size
            if i == band_from:
                block_dims = dims
    
            # Validate dimensions of bands block
            if block_dims != dims:
                self.logit("MSG: Block sizes don't match: %s != %s\n" % (str(block_dims), str(dims)))
        
        assert block_dims is not None, "Failed to calculate block size"
        return (int(block_dims[0]), int(block_dims[1]))
    
    def calculate_grid_size(self,  raster_size, block_size):
        """Dimensions of grid made up with blocks of requested size"""
    
        # Exact number of grid dimensions
        nx = float(raster_size[0]) / float(block_size[0])
        ny = float(raster_size[1]) / float(block_size[1])
    
        return ( int(math.ceil(nx)), int(math.ceil(ny)))
    
    def calculate_block_pad_size(self,  band, xoff, yoff, block_size):
        """Calculates number of columns [0] and rows [1] of padding""" 
        assert band is not None
    
        xpad = 0
        ypad= 0
        block_bound = ( xoff + block_size[0], yoff + block_size[1] )
    
        if block_bound[0] > band.XSize:
            xpad = block_bound[0] - band.XSize
        if block_bound[1] > band.YSize:
            ypad = block_bound[1] - band.YSize
    
        return (xpad, ypad)
    
    def get_gdal_geotransform(self,  ds):
        assert ds is not None
        gt = list(ds.GetGeoTransform())
        return tuple(gt)
    
    def calculate_geoxy(self,  gt, xy):
        """Calculate georeferenced coordinate from given x and y"""
        assert gt is not None
        assert xy is not None
        assert len(xy) == 2
    
        xgeo = gt[0] + gt[1] * xy[0] + gt[2] * xy[1];
        ygeo = gt[3] + gt[4] * xy[0] + gt[5] * xy[1];
    
        return (xgeo, ygeo)
    
    def calculate_geoxy_level(self,  gt, xy, level):
    
        # Update pixel resolution according to overview level
        newgt = ( gt[0], gt[1] * float(level), gt[2], gt[3], gt[4], gt[5] * float(level) )
    
        return self.calculate_geoxy(newgt, xy)
    
    def calculate_bounding_box(self,  ds, gt):
        """Calculate georeferenced coordinates of spatial extent of raster dataset"""
        assert ds is not None
    
        # UL, LL, UR, LR
        dim = ( (0,0),(0,ds.RasterYSize),(ds.RasterXSize,0),(ds.RasterXSize,ds.RasterYSize) )
    
        ext = (self.calculate_geoxy(gt, dim[0]), self.calculate_geoxy(gt, dim[1]),
               self.calculate_geoxy(gt, dim[2]), self.calculate_geoxy(gt, dim[3]))
    
        return ext
    
    def check_hex(self,  hex, bytes_size = None):
        assert hex is not None, "Error: Missing hex string"
        size = len(hex)
        assert size > 0, "Error: hex string is empty"
        assert size % 2 == 0, "Error: invalid size of hex string"
        if bytes_size is not None:
            n = int(size / 2)
            assert n == bytes_size, "Error: invalid number of bytes %d, expected %d" % (n, bytes_size)
    
    def dump_block_numpy(self,  pixels):
        assert pixels.ndim == 2
    #    print 'BEGIN BLOCK SCANLINES (numpy): (%d, %d)' % (len(pixels[0]), len(pixels))
    
        i = 0
        for row in range (0, len(pixels)):
            s = binascii.hexlify(pixels[row])
    #        print '%d (%d)\t%s' % (i, (len(s) / 2), s)
            i = i + 1
    
    #    print 'END BLOCK SCANLINES'
    
    def fetch_band_nodata(self,  band, default = 0):
        assert band is not None
    
        nodata = default
        if band.GetNoDataValue() is not None:
            nodata = band.GetNoDataValue()
        else:
            self.logit("WARNING: No nodata flagged in raster_columns metadata. "
                  "In serialized raster, nodata bytes will have value of 0.\n")
        return nodata
    
    def wkblify(self,  fmt, data):
        """Writes raw binary data into HEX-encoded string using binascii module."""
        import struct
    
        # Binary to HEX
        fmt_little = '<' +fmt
        hexstr = binascii.hexlify(struct.pack(fmt_little, data)).upper()
    
        # String'ify raw value for log
        valfmt = '\'' + self.fmt2printfmt(fmt[len(fmt) - 1]) + '\''
        val = valfmt % data
        self.logit('HEX (\'fmt=%s\', bytes=%d, val=%s):\t\t%s\n' \
              % (fmt, len(hexstr) / 2, str(val), hexstr))
    
        return hexstr
    
    def wkblify_raster_header(self,  options, ds, level, ulp, xsize = None, ysize = None):
        """Writes WKT Raster header based on given GDAL into HEX-encoded WKB."""
        assert ds is not None, "Error: Missing GDAL dataset"
        assert level >= 1
        assert len(ulp) == 2 is not None, "Error: invalid upper-left corner"
    
        if xsize is None or ysize is None:
            assert xsize is None and ysize is None
            xsize = ds.RasterXSize
            ysize = ds.RasterYSize
    
        # Collect GeoReference information
        gt = self.get_gdal_geotransform(ds)
        ul = self.calculate_geoxy(gt, (ulp[0], ulp[1]))
        rt_ip = ( ul[0], ul[1] )
        rt_skew = ( gt[2], gt[4] )
        rt_scale = ( gt[1] * level, gt[5] * level )
        
        # TODO: Any way to lookup for SRID based on SRS in WKT?
        #srs = osr.SpatialReference()
        #srs.ImportFromWkt(ds.GetProjection())
    
        # Burn input raster as WKTRaster WKB format
        hexwkb = ''
        ### Endiannes
        hexwkb += self.wkblify('B', options.endian)
        ### Version
        hexwkb += self.wkblify('H', options.version)
        ### Number of bands
        if options.band is not None and options.band > 0:
            hexwkb += self.wkblify('H', 1)
        else:
            hexwkb += self.wkblify('H', ds.RasterCount)
        self.check_hex(hexwkb, 5)
        ### Georeference
        hexwkb += self.wkblify('d', rt_scale[0])
        hexwkb += self.wkblify('d', rt_scale[1])
        hexwkb += self.wkblify('d', rt_ip[0])
        hexwkb += self.wkblify('d', rt_ip[1])
        hexwkb += self.wkblify('d', rt_skew[0])
        hexwkb += self.wkblify('d', rt_skew[1])
        hexwkb += self.wkblify('i', options.srid)
        self.check_hex(hexwkb, 57)
        ### Number of columns and rows
        hexwkb += self.wkblify('H', xsize)
        hexwkb += self.wkblify('H', ysize)
        self.check_hex(hexwkb, 61)
    
        self.logit("MSG: Georeference: px = %s -> ul = %s \tresolution = %s \trotation = %s\n" \
              % (str(ulp), str(rt_ip), str(rt_scale), str(rt_skew)))
        return hexwkb
    
    def wkblify_band_header(self,  options, band):
        """Writes band header into HEX-encoded WKB"""
        assert band is not None, "Error: Missing GDAL raster band"
    
        hexwkb = ""
    
        first4bits = 0
        
        # If the register option is enabled, set the first bit to 1
        if options.register:
            first4bits = 128
            
        nodata = band.GetNoDataValue()
        # If there is no nodata value, set it to 0. Otherwise set the HasNodata bit to 1
        if nodata is not None:
            first4bits += 64
        else:
            nodata = 0
        
        # Encode pixel type
        pixtype = self.gdt2pt(band.DataType)['id']
        hexwkb += self.wkblify('B', pixtype + first4bits)
        
        # Encode nodata value (or Zero, if nodata unavailable) 
        hexwkb += self.wkblify(self.pt2fmt(pixtype), nodata)
    
        self.check_hex(hexwkb)
        return hexwkb
    
    def wkblify_band(self,  options, band, level, xoff, yoff, read_block_size, block_size, infile, bandidx):
        """Writes band of given GDAL dataset into HEX-encoded WKB for WKT Raster output."""
        assert band is not None, "Error: Missing GDAL raster band"
    
        hexwkb = ''
        
        if options.register:
            # Off-db raster
            # TODO: Do we want to handle options.overview_level? --mloskot
            # ANSWER: 
            # TODO: Where bandidx and ds come from? --mloskot
            # ANSWER: Provided by caller method --jorgearevalo
            hexwkb += self.wkblify('B', bandidx - 1)
            filepath = os.path.abspath(infile.replace('\\', '\\\\'))
            self.logit('MSG: Out-db raster path=%s\n' % filepath)
            hexwkb += self.wkblify(str(len(filepath)) + 's', filepath)
            hexwkb += self.wkblify('B', 0)
        else:
            # In-db raster
    
            # Right most column and bottom most row of blocks have
            # portions that extend beyond the raster
            read_padding_size = self.calculate_block_pad_size(band, xoff, yoff, read_block_size)
            valid_read_block_size = ( read_block_size[0] - read_padding_size[0],
                                      read_block_size[1] - read_padding_size[1] )
    
    
            if read_padding_size[0] > 0 or read_padding_size[1] > 0:
                target_block_size = (valid_read_block_size[0] / level, valid_read_block_size[1] / level)
                target_padding_size = (read_padding_size[0] / level, read_padding_size[1] / level)
            else:
                target_block_size = block_size
                target_padding_size = ( 0, 0 )
    
            self.logit('MSG: Normalize read_block=%s for level=%d to valid_read_block=%s with padding=%s\n' % \
                  (read_block_size, level, valid_read_block_size, read_padding_size))
            self.logit('MSG: Normalize target_block=%s for level=%d to valid_target_block=%s with padding=%s\n' % \
                  (block_size, level, target_block_size, target_padding_size))
            self.logit('MSG: ReadAsArray( %d, %d, %s, %s)\n' % \
                  (xoff, yoff, str(valid_read_block_size), str(target_block_size)))
    
            assert valid_read_block_size[0] > 0 and valid_read_block_size[1] > 0
            assert target_block_size[0] > 0 and target_block_size[1] > 0
    
            pixels = band.ReadAsArray(xoff, yoff, valid_read_block_size[0], valid_read_block_size[1],
                                      target_block_size[0], target_block_size[1])
    
            # XXX: Use for debugging only
            #dump_block_numpy(pixels)
    
            out_pixels = numpy.zeros((block_size[1], block_size[0]), self.pt2numpy(band.DataType))
    
            self.logit('MSG: Read valid source:\t%d x %d\n' % (len(pixels[0]), len(pixels)))
            self.logit('MSG: Write into block:\t%d x %d\n' % (len(out_pixels[0]), len(out_pixels)))
            
            if target_padding_size[0] > 0 or target_padding_size[1] > 0:
    
                ysize_read_pixels = len(pixels)
                nodata_value = fetch_band_nodata(band)
    
                # Apply columns padding
                pad_cols = numpy.array([nodata_value] * target_padding_size[0])
                for row in range (0, ysize_read_pixels):
                    out_line = numpy.append(pixels[row], pad_cols)
                    out_pixels[row] = out_line
    
                # Fill rows padding with nodata value
                for row in range(ysize_read_pixels, ysize_read_pixels + target_padding_size[1]):
                    out_pixels[row].fill(nodata_value)
            else:
                out_pixels = pixels
    
            # XXX: Use for debugging only
            #dump_block_numpy(out_pixels)
    
            hexwkb = binascii.hexlify(out_pixels)
    
        self.check_hex(hexwkb)
        return hexwkb
    
    def wkblify_raster_level(self,  options, ds, level, band_range, infile, i):
#        assert ds is not None
#        assert level >= 1
#        assert len(band_range) == 2
    
        band_from = band_range[0]
        band_to = band_range[1]
        
        # Collect raster and block dimensions
        raster_size = ( ds.RasterXSize, ds.RasterYSize )
#        if options.block_size is not None:
#            block_size = parse_block_size(options)
#            read_block_size = ( block_size[0] * level, block_size[1] * level)
#            grid_size = calculate_grid_size(raster_size, read_block_size)
#        else:
        block_size = raster_size # Whole raster as a single block
        read_block_size = block_size
        grid_size = (1, 1)
#        end else
        
    
#        self.logit("MSG: Processing raster=%s using read_block_size=%s block_size=%s of grid=%s in level=%d\n" % \
#              (str(raster_size), str(read_block_size), str(block_size), str(grid_size), level))
    
        # Register base raster in RASTER_COLUMNS - SELECT AddRasterColumn();
        if level == 1:
            if i == 0 and options.create_table:
                gt = self.get_gdal_geotransform(ds)
                pixel_size = ( gt[1], gt[5] )
                pixel_types = self.collect_pixel_types(ds, band_from, band_to)
                nodata_values = self.collect_nodata_values(ds, band_from, band_to)
                extent = self.calculate_bounding_box(ds, gt)
                sql = self.make_sql_addrastercolumn(options, pixel_types, nodata_values,
                                               pixel_size, block_size, extent)
#                self.upload_string += sql
            gen_table = options.table
            
        else:
            # Create overview table and register in RASTER_OVERVIEWS
    
            # CREATE TABLE o_<LEVEL>_<NAME> ( rid serial, options.column RASTER )
            schema_table_names = self.make_sql_schema_table_names(options.table)
            level_table_name = 'o_' + str(level) + '_' + schema_table_names[1] 
            level_table = schema_table_names[0] + '.' + level_table_name       
            if i == 0:
                sql = self.make_sql_create_table(options, level_table, True)
                upload_strin += sql
                sql = self.make_sql_register_overview(options, level_table_name, level)
                self.upload_string += sql
                
            gen_table = level_table
    
        # Write (original) raster to hex binary output
        tile_count = 0
        hexwkb = ''
    
        for ycell in range(0, grid_size[1]):
            for xcell in range(0, grid_size[0]):
    
                xoff = xcell * read_block_size[0]
                yoff = ycell * read_block_size[1]
    
                self.logit("MSG: --------- CELL #%04d\tindex = %d x %d\tdim = (%d x %d)\t(%d x %d) \t---------\n" % \
                      (tile_count, xcell, ycell, xoff, yoff, xoff + read_block_size[0], yoff + read_block_size[1]))
            
                if options.block_size is not None:
                    hexwkb = '' # Reset buffer as single INSERT per tile is generated
                    hexwkb += self.wkblify_raster_header(options, ds, level, (xoff, yoff),
                                                    block_size[0], block_size[1])
                else:
                    hexwkb += self.wkblify_raster_header(options, ds, level, (xoff, yoff))
    
                for b in range(band_from, band_to):
                    band = ds.GetRasterBand(b)
                    assert band is not None, "Missing GDAL raster band %d" % b
                    self.logit("MSG: Band %d\n" % b)
    
                    hexwkb += self.wkblify_band_header(options, band)
                    hexwkb += self.wkblify_band(options, band, level, xoff, yoff, read_block_size, block_size, infile, b)
    
                # INSERT INTO
                self.check_hex(hexwkb) # TODO: Remove to not to decrease performance
                sql = self.make_sql_insert_raster(gen_table, options.column, hexwkb)
                self.upload_string += sql
                
                tile_count = tile_count + 1
    
        return (gen_table, tile_count)
    
    def wkblify_raster(self, options,  infile, i, previous_gt = None):
        """Writes given raster dataset using GDAL features into HEX-encoded of
        WKB for WKT Raster output."""
        # Open source raster file
        ds = gdal.Open(infile, gdalc.GA_ReadOnly);
        if ds is None:
            QMessageBox.warning(None, 'Error:', 'Cannot open input file: ' + str(infile))
    
        # By default, translate all raster bands
        band_range = ( 1, ds.RasterCount + 1 )
    
        # Compare this px size with previous one
        current_gt = self.get_gdal_geotransform(ds)
        if previous_gt is not None:
            if previous_gt[1] != current_gt[1] or previous_gt[5] != current_gt[5]:
                QMessageBox.warning(None, 'Error','Cannot load raster with different pixel size in the same raster table')
    
        # Generate requested overview level (base raster if level = 1)
        summary = self.wkblify_raster_level(options, ds, options.overview_level, band_range, infile, i)
        
        # Cleanup
        ds = None
        return current_gt
           
