# -*- coding: utf-8 -*-
"""
/***************************************************************************
OpenLayers Plugin
A QGIS plugin

                             -------------------
begin                : 2009-11-30
copyright            : (C) 2009 by Pirmin Kalberer, Sourcepole
email                : pka at sourcepole.ch
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
# Import the PyQt and QGIS libraries
from qgis.PyQt.QtCore import *
from qgis.PyQt.QtWidgets import *
from qgis.PyQt.QtGui import *
from qgis.core import *
#import resources_rc
import imp
from openlayers_plugin.openlayers_layer import OpenlayersLayer
from openlayers_plugin.openlayers_plugin_layer_type import OpenlayersPluginLayerType
from openlayers_plugin.weblayers.weblayer_registry import WebLayerTypeRegistry
from openlayers_plugin.weblayers.google_maps import OlGooglePhysicalLayer, OlGoogleStreetsLayer, OlGoogleHybridLayer, OlGoogleSatelliteLayer
from openlayers_plugin.weblayers.osm_thunderforest import OlOpenCycleMapLayer, OlOCMLandscapeLayer, OlOCMPublicTransportLayer, OlOCMOutdoorstLayer, OlOCMTransportDarkLayer, OlOCMSpinalMapLayer, OlOCMPioneerLayer, OlOCMMobileAtlasLayer, OlOCMNeighbourhoodLayer
from openlayers_plugin.weblayers.osm import OlOpenStreetMapLayer, OlOSMHumanitarianDataModelLayer
from openlayers_plugin.weblayers.bing_maps import OlBingRoadLayer, OlBingAerialLayer, OlBingAerialLabelledLayer
from openlayers_plugin.weblayers.apple_maps import OlAppleiPhotoMapLayer
from openlayers_plugin.weblayers.osm_stamen import OlOSMStamenTonerLayer, OlOSMStamenWatercolorLayer, OlOSMStamenTerrainLayer
#from openlayers_plugin.weblayers.map_quest import OlMapQuestOSMLayer, OlMapQuestOpenAerialLayer


class OpenlayersMenu(QMenu):
    def __init__(self, iface, parent=None):
        QMenu.__init__(self, parent)
        self.iface = iface

        self._olLayerTypeRegistry = WebLayerTypeRegistry(self)

        self._olLayerTypeRegistry.register(OlGooglePhysicalLayer())
        self._olLayerTypeRegistry.register(OlGoogleStreetsLayer())
        self._olLayerTypeRegistry.register(OlGoogleHybridLayer())
        self._olLayerTypeRegistry.register(OlGoogleSatelliteLayer())

        self._olLayerTypeRegistry.register(OlOpenStreetMapLayer())
        self._olLayerTypeRegistry.register(OlOSMHumanitarianDataModelLayer())

        self._olLayerTypeRegistry.register(OlOpenCycleMapLayer())
        self._olLayerTypeRegistry.register(OlOCMLandscapeLayer())
        self._olLayerTypeRegistry.register(OlOCMPublicTransportLayer())
        self._olLayerTypeRegistry.register(OlOCMOutdoorstLayer())
        self._olLayerTypeRegistry.register(OlOCMTransportDarkLayer())
        self._olLayerTypeRegistry.register(OlOCMSpinalMapLayer())
        self._olLayerTypeRegistry.register(OlOCMPioneerLayer())
        self._olLayerTypeRegistry.register(OlOCMMobileAtlasLayer())
        self._olLayerTypeRegistry.register(OlOCMNeighbourhoodLayer())

        self._olLayerTypeRegistry.register(OlBingRoadLayer())
        self._olLayerTypeRegistry.register(OlBingAerialLayer())
        self._olLayerTypeRegistry.register(OlBingAerialLabelledLayer())

        self._olLayerTypeRegistry.register(OlOSMStamenTonerLayer())
        self._olLayerTypeRegistry.register(OlOSMStamenWatercolorLayer())
        self._olLayerTypeRegistry.register(OlOSMStamenTerrainLayer())

#        self._olLayerTypeRegistry.register(OlMapQuestOSMLayer())
#        self._olLayerTypeRegistry.register(OlMapQuestOpenAerialLayer())

        self._olLayerTypeRegistry.register(OlAppleiPhotoMapLayer())

        for group in self._olLayerTypeRegistry.groups():
            groupMenu = group.menu()
            for layer in self._olLayerTypeRegistry.groupLayerTypes(group):
                layer.addMenuEntry(groupMenu, self.iface.mainWindow())
            self.addMenu(groupMenu)

        # Register plugin layer type
        self.pluginLayerType = OpenlayersPluginLayerType(
            self.iface, self.setReferenceLayer, self._olLayerTypeRegistry)
        QgsApplication.pluginLayerRegistry().addPluginLayerType(self.pluginLayerType)

    def addLayer(self, layerType):
        layer = None
        if layerType.hasXYZUrl():
            xyzUrl = layerType.xyzUrlConfig()
            layer = QgsRasterLayer(
                'url=' + xyzUrl + '&type=xyz', layerType.displayName, 'wms')
        else:
            layer = OpenlayersLayer(self.iface, self._olLayerTypeRegistry)
            layer.setName(layerType.displayName)
            layer.setLayerType(layerType)

        if not layer.isValid():
            return

        coordRefSys = layerType.coordRefSys(self.canvasCrs())
        self.setMapCrs(coordRefSys)
        QgsProject.instance().addMapLayer(layer, False)
        legendRootGroup = self.iface.layerTreeView().layerTreeModel().rootGroup()
        legendRootGroup.insertLayer(len(legendRootGroup.children()), layer)

        # last added layer is new reference
        self.setReferenceLayer(layer)

    def setReferenceLayer(self, layer):
        self.layer = layer

    def removeLayer(self, layerId):
        if self.layer is not None:
            if QGis.QGIS_VERSION_INT >= 10900:
                if self.layer.id() == layerId:
                    self.layer = None
            else:
                if self.layer.getLayerID() == layerId:
                    self.layer = None

    def canvasCrs(self):
        mapCanvas = self.iface.mapCanvas()
        crs = mapCanvas.mapSettings().destinationCrs()
        return crs

    def setMapCrs(self, coordRefSys):
        mapCanvas = self.iface.mapCanvas()
        canvasCrs = self.canvasCrs()
        if canvasCrs != coordRefSys:
            coordTrans = QgsCoordinateTransform(
                canvasCrs, coordRefSys,  QgsProject.instance())
            extMap = mapCanvas.extent()
            extMap = coordTrans.transform(
                extMap, QgsCoordinateTransform.ForwardTransform)
            QgsProject.instance().setCrs(coordRefSys)
            mapCanvas.freeze(False)
            mapCanvas.setExtent(extMap)
