# qgis-ol3 Creates OpenLayers map from QGIS layers
# Copyright (C) 2014 Victor Olaya (volayaf@gmail.com)
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import os
import re
from datetime import datetime
import shutil
import traceback
import xml.etree.ElementTree
from urlparse import parse_qs
from qgis.core import (QgsProject,
                       QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform,
                       QgsDataSourceURI,
                       QgsRectangle,
                       QgsCsException,
                       QgsMessageLog)
from utils import (exportLayers, safeName, replaceInTemplate,
                   is25d, ALL_ATTRIBUTES)
from exp2js import compile_to_file
from qgis.utils import iface
from PyQt4.QtCore import (Qt,
                          QDir)
from PyQt4.QtCore import QObject
from PyQt4.QtGui import (QApplication,
                         QCursor)
from olLayerScripts import writeLayersAndGroups
from olScriptStrings import (measureScript,
                             measuringScript,
                             measureControlScript,
                             measureUnitMetricScript,
                             measureUnitFeetScript,
                             measureStyleScript)
from olStyleScripts import exportStyles
from writer import (Writer,
                    translator)


class OpenLayersWriter(Writer):

    """
    Writer for creation of web maps based on the OpenLayers
    JavaScript library.
    """

    def __init__(self):
        super(OpenLayersWriter, self).__init__()

    @classmethod
    def type(cls):
        return 'openlayers'

    @classmethod
    def name(cls):
        return QObject.tr(translator, 'OpenLayers')

    def write(self, iface, dest_folder):
        self.preview_file = self.writeOL(iface, layers=self.layers,
                                         groups=self.groups,
                                         popup=self.popup,
                                         visible=self.visible,
                                         json=self.json,
                                         clustered=self.cluster,
                                         settings=self.params,
                                         folder=dest_folder)
        return self.preview_file

    @classmethod
    def writeOL(cls, iface, layers, groups, popup, visible,
                json, clustered, settings, folder):
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        controlCount = 0
        stamp = datetime.now().strftime("%Y_%m_%d-%H_%M_%S_%f")
        folder = os.path.join(folder, 'qgis2web_' + unicode(stamp))
        imagesFolder = os.path.join(folder, "images")
        QDir().mkpath(imagesFolder)
        restrictToExtent = settings["Scale/Zoom"]["Restrict to extent"]
        try:
            dst = os.path.join(folder, "resources")
            if not os.path.exists(dst):
                shutil.copytree(os.path.join(os.path.dirname(__file__),
                                             "resources"),
                                dst)
            matchCRS = settings["Appearance"]["Match project CRS"]
            precision = settings["Data export"]["Precision"]
            optimize = settings["Data export"]["Minify GeoJSON files"]
            extent = settings["Scale/Zoom"]["Extent"]
            exportLayers(iface, layers, folder, precision,
                         optimize, popup, json, restrictToExtent, extent)
            exportStyles(layers, folder, clustered)
            osmb = writeLayersAndGroups(layers, groups, visible, folder, popup,
                                        settings, json, matchCRS, clustered,
                                        iface, restrictToExtent, extent)
            jsAddress = '<script src="resources/polyfills.js"></script>'
            if settings["Data export"]["Mapping library location"] == "Local":
                cssAddress = """<link rel="stylesheet" """
                cssAddress += """href="./resources/ol.css" />"""
                jsAddress += """
        <script src="./resources/ol.js"></script>"""
            else:
                cssAddress = """<link rel="stylesheet" href="http://"""
                cssAddress += "cdnjs.cloudflare.com/ajax/libs/openlayers/"
                cssAddress += """4.0.1/ol.css" />"""
                jsAddress += """
        <script src="https://cdnjs.cloudflare.com/ajax/libs/openlayers/"""
                jsAddress += """4.0.1/ol.js"></script>"""
            layerSearch = unicode(settings["Appearance"]["Layer search"])
            if layerSearch != "None" and layerSearch != "":
                searchLayer = settings["Appearance"]["Search layer"]
                cssAddress += """
        <link rel="stylesheet" href="resources/horsey.min.css">
        <link rel="stylesheet" href="resources/ol3-search-layer.min.css">"""
                jsAddress += """
        <script src="http://cdn.polyfill.io/v2/polyfill.min.js?features="""
                jsAddress += """Element.prototype.classList,URL"></script>
        <script src="resources/horsey.min.js"></script>
        <script src="resources/ol3-search-layer.min.js"></script>"""
                searchVals = layerSearch.split(": ")
                layerSearch = u"""
    var searchLayer = new ol.SearchLayer({{
      layer: lyr_{layer},
      colName: '{field}',
      zoom: 10,
      collapsed: true,
      map: map
    }});

    map.addControl(searchLayer);""".format(layer=searchLayer,
                                           field=searchVals[1])
                controlCount = controlCount + 1
            else:
                layerSearch = ""
            if osmb != "":
                jsAddress += """
        <script src="resources/OSMBuildings-OL3.js"></script>"""
            geojsonVars = ""
            wfsVars = ""
            styleVars = ""
            for count, (layer, encode2json) in enumerate(zip(layers, json)):
                sln = safeName(layer.name()) + unicode(count)
                if layer.type() == layer.VectorLayer:
                    if layer.providerType() != "WFS" or encode2json:
                        geojsonVars += ('<script src="layers/%s"></script>' %
                                        (sln + ".js"))
                    else:
                        layerSource = layer.source()
                        if ("retrictToRequestBBOX" in layerSource or
                                "restrictToRequestBBOX" in layerSource):
                            provider = layer.dataProvider()
                            uri = QgsDataSourceURI(provider.dataSourceUri())
                            wfsURL = uri.param("url")
                            wfsTypename = uri.param("typename")
                            wfsSRS = uri.param("srsname")
                            layerSource = wfsURL
                            layerSource += "?SERVICE=WFS&VERSION=1.0.0&"
                            layerSource += "REQUEST=GetFeature&TYPENAME="
                            layerSource += wfsTypename
                            layerSource += "&SRSNAME="
                            layerSource += wfsSRS
                        if not matchCRS:
                            layerSource = re.sub('SRSNAME\=EPSG\:\d+',
                                                 'SRSNAME=EPSG:3857',
                                                 layerSource)
                        layerSource += "&outputFormat=text%2Fjavascript&"
                        layerSource += "format_options=callback%3A"
                        layerSource += "get" + sln + "Json"
                        wfsVars += ('<script src="%s"></script>' % layerSource)
                    styleVars += ('<script src="styles/%s_style.js">'
                                  '</script>' %
                                  (sln))
            popupLayers = "popupLayers = [%s];" % ",".join(
                ['1' for field in popup])
            controls = ['expandedAttribution']
            project = QgsProject.instance()
            if project.readBoolEntry("ScaleBar", "/Enabled", False)[0]:
                controls.append("new ol.control.ScaleLine({})")
            if settings["Appearance"]["Measure tool"] != "None":
                controls.append(
                    'new measureControl()')
            if settings["Appearance"]["Geolocate user"]:
                controls.append(
                    'new geolocateControl()')
            if (settings["Appearance"]["Add layers list"] and
                    settings["Appearance"]["Add layers list"] != "" and
                    settings["Appearance"]["Add layers list"] != "None"):
                layersList = """
var layerSwitcher = new ol.control.LayerSwitcher({tipLabel: "Layers"});
map.addControl(layerSwitcher);"""
                if settings["Appearance"]["Add layers list"] == "Expanded":
                    layersList += """
layerSwitcher.hidePanel = function() {};
layerSwitcher.showPanel();
"""
            else:
                layersList = ""
            pageTitle = project.title()
            mapSettings = iface.mapCanvas().mapSettings()
            backgroundColor = """
        <style>
        html, body {{
            background-color: {bgcol};
        }}
        </style>
""".format(bgcol=mapSettings.backgroundColor().name())
            geolocateUser = settings["Appearance"]["Geolocate user"]
            (geolocateCode, controlCount) = geolocateStyle(geolocateUser,
                                                           controlCount)
            backgroundColor += geolocateCode
            mapbounds = bounds(iface,
                               extent == "Canvas extent",
                               layers,
                               settings["Appearance"]["Match project CRS"])
            mapextent = "extent: %s," % mapbounds if restrictToExtent else ""
            maxZoom = int(settings["Scale/Zoom"]["Max zoom level"])
            minZoom = int(settings["Scale/Zoom"]["Min zoom level"])
            popupsOnHover = settings["Appearance"]["Show popups on hover"]
            highlightFeatures = settings["Appearance"]["Highlight on hover"]
            onHover = unicode(popupsOnHover).lower()
            highlight = unicode(highlightFeatures).lower()
            highlightFill = mapSettings.selectionColor().name()
            proj4 = ""
            proj = ""
            view = "%s maxZoom: %d, minZoom: %d" % (
                mapextent, maxZoom, minZoom)
            if settings["Appearance"]["Match project CRS"]:
                proj4 = """
<script src="http://cdnjs.cloudflare.com/ajax/libs/proj4js/2.3.6/proj4.js">"""
                proj4 += "</script>"
                proj = "<script>proj4.defs('{epsg}','{defn}');</script>"\
                    .format(
                        epsg=mapSettings.destinationCrs().authid(),
                        defn=mapSettings.destinationCrs().toProj4())
                view += ", projection: '%s'" % (
                    mapSettings.destinationCrs().authid())
            if settings["Appearance"]["Measure tool"] != "None":
                measureControl = measureControlScript()
                measuring = measuringScript()
                measure = measureScript()
                if settings["Appearance"]["Measure tool"] == "Imperial":
                    measureUnit = measureUnitFeetScript()
                else:
                    measureUnit = measureUnitMetricScript()
                measureStyle = measureStyleScript(controlCount)
                controlCount = controlCount + 1
            else:
                measureControl = ""
                measuring = ""
                measure = ""
                measureUnit = ""
                measureStyle = ""
            geolocateHead = geolocationHead(geolocateUser)
            geolocate = geolocation(geolocateUser)
            geocode = settings["Appearance"]["Add address search"]
            geocodingLinks = geocodeLinks(geocode)
            geocodingJS = geocodeJS(geocode)
            geocodingScript = geocodeScript(geocode)
            extracss = """
        <link rel="stylesheet" href="./resources/ol3-layerswitcher.css">
        <link rel="stylesheet" href="./resources/qgis2web.css">"""
            if geocode:
                geocodePos = 65 + (controlCount * 35)
                extracss += """
        <style>
        .ol-geocoder.gcd-gl-container {
            top: %dpx!important;
        }
        .ol-geocoder .gcd-gl-btn {
            width: 21px!important;
            height: 21px!important;
        }
        </style>""" % geocodePos
            if settings["Appearance"]["Geolocate user"]:
                extracss += """
        <link rel="stylesheet" href="http://maxcdn.bootstrapcdn.com/"""
                extracss += """font-awesome/4.6.3/css/font-awesome.min.css">"""
            ol3layerswitcher = """
        <script src="./resources/ol3-layerswitcher.js"></script>"""
            ol3popup = """<div id="popup" class="ol-popup">
                <a href="#" id="popup-closer" class="ol-popup-closer"></a>
                <div id="popup-content"></div>
            </div>"""
            ol3qgis2webjs = """<script src="./resources/qgis2web.js"></script>
        <script src="./resources/Autolinker.min.js"></script>"""
            if osmb != "":
                ol3qgis2webjs += """
        <script>{osmb}</script>""".format(osmb=osmb)
            ol3layers = """
        <script src="./layers/layers.js" type="text/javascript"></script>"""
            mapSize = iface.mapCanvas().size()
            exp_js = """
        <script src="resources/qgis2web_expressions.js"></script>"""
            values = {"@PAGETITLE@": pageTitle,
                      "@CSSADDRESS@": cssAddress,
                      "@EXTRACSS@": extracss,
                      "@JSADDRESS@": jsAddress,
                      "@MAP_WIDTH@": unicode(mapSize.width()) + "px",
                      "@MAP_HEIGHT@": unicode(mapSize.height()) + "px",
                      "@OL3_STYLEVARS@": styleVars,
                      "@OL3_BACKGROUNDCOLOR@": backgroundColor,
                      "@OL3_POPUP@": ol3popup,
                      "@OL3_GEOJSONVARS@": geojsonVars,
                      "@OL3_WFSVARS@": wfsVars,
                      "@OL3_PROJ4@": proj4,
                      "@OL3_PROJDEF@": proj,
                      "@OL3_GEOCODINGLINKS@": geocodingLinks,
                      "@OL3_GEOCODINGJS@": geocodingJS,
                      "@QGIS2WEBJS@": ol3qgis2webjs,
                      "@OL3_LAYERSWITCHER@": ol3layerswitcher,
                      "@OL3_LAYERS@": ol3layers,
                      "@OL3_MEASURESTYLE@": measureStyle,
                      "@EXP_JS@": exp_js,
                      "@LEAFLET_ADDRESSCSS@": "",
                      "@LEAFLET_MEASURECSS@": "",
                      "@LEAFLET_EXTRAJS@": "",
                      "@LEAFLET_ADDRESSJS@": "",
                      "@LEAFLET_MEASUREJS@": "",
                      "@LEAFLET_CRSJS@": "",
                      "@LEAFLET_LAYERSEARCHCSS@": "",
                      "@LEAFLET_LAYERSEARCHJS@": "",
                      "@LEAFLET_CLUSTERCSS@": "",
                      "@LEAFLET_CLUSTERJS@": ""}
            with open(os.path.join(folder, "index.html"), "w") as f:
                htmlTemplate = settings["Appearance"]["Template"]
                if htmlTemplate == "":
                    htmlTemplate = "basic"
                templateOutput = replaceInTemplate(
                    htmlTemplate + ".html", values)
                templateOutput = re.sub('\n[\s_]+\n', '\n', templateOutput)
                f.write(templateOutput)
            values = {"@GEOLOCATEHEAD@": geolocateHead,
                      "@BOUNDS@": mapbounds,
                      "@CONTROLS@": ",".join(controls),
                      "@LAYERSLIST@": layersList,
                      "@POPUPLAYERS@": popupLayers,
                      "@VIEW@": view,
                      "@LAYERSEARCH@": layerSearch,
                      "@ONHOVER@": onHover,
                      "@DOHIGHLIGHT@": highlight,
                      "@HIGHLIGHTFILL@": highlightFill,
                      "@GEOLOCATE@": geolocate,
                      "@GEOCODINGSCRIPT@": geocodingScript,
                      "@MEASURECONTROL@": measureControl,
                      "@MEASURING@": measuring,
                      "@MEASURE@": measure,
                      "@MEASUREUNIT@": measureUnit}
            with open(os.path.join(folder, "resources", "qgis2web.js"),
                      "w") as f:
                out = replaceInScript("qgis2web.js", values)
                f.write(out.encode("utf-8"))
        except Exception as e:
            QgsMessageLog.logMessage(traceback.format_exc(), "qgis2web",
                                     level=QgsMessageLog.CRITICAL)
        finally:
            QApplication.restoreOverrideCursor()
        return os.path.join(folder, "index.html")


def replaceInScript(template, values):
    path = os.path.join(os.path.dirname(__file__), "resources", template)
    with open(path) as f:
        lines = f.readlines()
    s = "".join(lines)
    for name, value in values.iteritems():
        s = s.replace(name, value)
    return s


def bounds(iface, useCanvas, layers, matchCRS):
    if useCanvas:
        canvas = iface.mapCanvas()
        try:
            canvasCrs = canvas.mapSettings().destinationCrs()
        except:
            canvasCrs = canvas.mapRenderer().destinationCrs()
        if not matchCRS:
            transform = QgsCoordinateTransform(canvasCrs,
                                               QgsCoordinateReferenceSystem(
                                                   "EPSG:3857"))
            try:
                extent = transform.transform(canvas.extent())
            except QgsCsException:
                extent = QgsRectangle(-20026376.39, -20048966.10,
                                      20026376.39, 20048966.10)
        else:
            extent = canvas.extent()
    else:
        extent = None
        for layer in layers:
            if not matchCRS:
                epsg3857 = QgsCoordinateReferenceSystem("EPSG:3857")
                transform = QgsCoordinateTransform(layer.crs(), epsg3857)
                try:
                    layerExtent = transform.transform(layer.extent())
                except QgsCsException:
                    layerExtent = QgsRectangle(-20026376.39, -20048966.10,
                                               20026376.39, 20048966.10)
            else:
                layerExtent = layer.extent()
            if extent is None:
                extent = layerExtent
            else:
                extent.combineExtentWith(layerExtent)

    return "[%f, %f, %f, %f]" % (extent.xMinimum(), extent.yMinimum(),
                                 extent.xMaximum(), extent.yMaximum())


def geolocation(geolocate):
    if geolocate:
        return """
      var geolocation = new ol.Geolocation({
  projection: map.getView().getProjection()
});


var accuracyFeature = new ol.Feature();
geolocation.on('change:accuracyGeometry', function() {
  accuracyFeature.setGeometry(geolocation.getAccuracyGeometry());
});

var positionFeature = new ol.Feature();
positionFeature.setStyle(new ol.style.Style({
  image: new ol.style.Circle({
    radius: 6,
    fill: new ol.style.Fill({
      color: '#3399CC'
    }),
    stroke: new ol.style.Stroke({
      color: '#fff',
      width: 2
    })
  })
}));

geolocation.on('change:position', function() {
  var coordinates = geolocation.getPosition();
  positionFeature.setGeometry(coordinates ?
      new ol.geom.Point(coordinates) : null);
});

var geolocateOverlay = new ol.layer.Vector({
  source: new ol.source.Vector({
    features: [accuracyFeature, positionFeature]
  })
});

geolocation.setTracking(true);
"""
    else:
        return ""


def geolocationHead(geolocate):
    if geolocate:
        return """
isTracking = false;
geolocateControl = function(opt_options) {
    var options = opt_options || {};
    var button = document.createElement('button');
    button.className += ' fa fa-map-marker';
    var handleGeolocate = function() {
        if (isTracking) {
            map.removeLayer(geolocateOverlay);
            isTracking = false;
      } else if (geolocation.getTracking()) {
            map.addLayer(geolocateOverlay);
            map.getView().setCenter(geolocation.getPosition());
            isTracking = true;
      }
    };
    button.addEventListener('click', handleGeolocate, false);
    button.addEventListener('touchstart', handleGeolocate, false);
    var element = document.createElement('div');
    element.className = 'geolocate ol-unselectable ol-control';
    element.appendChild(button);
    ol.control.Control.call(this, {
        element: element,
        target: options.target
    });
};
ol.inherits(geolocateControl, ol.control.Control);"""
    else:
        return ""


def geolocateStyle(geolocate, controlCount):
    if geolocate:
        ctrlPos = 65 + (controlCount * 35)
        touchCtrlPos = 80 + (controlCount * 50)
        controlCount = controlCount + 1
        return ("""
        <style>
        .geolocate {
            top: %dpx;
            left: .5em;
        }
        .ol-touch .geolocate {
            top: %dpx;
        }
        </style>""" % (ctrlPos, touchCtrlPos), controlCount)
    else:
        return ("", controlCount)


def geocodeLinks(geocode):
    if geocode:
        returnVal = """
    <link href="http://cdn.jsdelivr.net/openlayers.geocoder/latest/"""
        returnVal += """ol3-geocoder.min.css" rel="stylesheet">"""
        return returnVal
    else:
        return ""


def geocodeJS(geocode):
    if geocode:
        returnVal = """
    <script src="http://cdn.jsdelivr.net/openlayers.geocoder/latest/"""
        returnVal += """ol3-geocoder.js"></script>"""
        return returnVal
    else:
        return ""


def geocodeScript(geocode):
    if geocode:
        return """
var geocoder = new Geocoder('nominatim', {
  provider: 'osm',
  lang: 'en-US',
  placeholder: 'Search for ...',
  limit: 5,
  keepOpen: true
});
map.addControl(geocoder);"""
    else:
        return ""
