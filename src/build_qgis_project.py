"""Build a styled QGIS project for an exported SNAP run. Run with QGIS's Python, e.g.

  & "C:\\Program Files\\QGIS 3.44.15\\bin\\python-qgis-ltr.bat" src\\build_qgis_project.py --run-id tx_trial_01

Reads outputs/qgis/<run-id>/ (from export_qgis_layers.py) and writes qgis/<run-id>.qgz
with relative paths. Display stretches are for viewing only, not analysis thresholds.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from qgis.core import (
    QgsApplication, QgsColorRampShader, QgsMapLayer, QgsContrastEnhancement, QgsCoordinateReferenceSystem,
    QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol, QgsMultiBandColorRenderer, QgsPalettedRasterRenderer, QgsProject, QgsRasterLayer,
    QgsRasterShader, QgsReferencedRectangle, QgsSingleBandGrayRenderer, QgsSingleBandPseudoColorRenderer,
    QgsVectorLayer,
)
from qgis.PyQt.QtGui import QColor

ROOT = Path(__file__).resolve().parents[1]
STRETCH_DB = {"VH": (-25.0, -10.0), "VV": (-20.0, -5.0)}


def contrast(provider, band, lo, hi):
    ce = QgsContrastEnhancement(provider.dataType(band))
    ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
    ce.setMinimumValue(lo)
    ce.setMaximumValue(hi)
    return ce


def raster(path: Path, name: str) -> QgsRasterLayer:
    layer = QgsRasterLayer(str(path), name)
    if not layer.isValid():
        raise RuntimeError(f"QGIS could not open {path}")
    return layer


def grey(layer, lo, hi):
    renderer = QgsSingleBandGrayRenderer(layer.dataProvider(), 1)
    renderer.setContrastEnhancement(contrast(layer.dataProvider(), 1, lo, hi))
    layer.setRenderer(renderer)


def diverging(layer, limit=6.0):
    shader = QgsColorRampShader(-limit, limit)
    shader.setColorRampType(QgsColorRampShader.Interpolated)
    shader.setColorRampItemList([
        QgsColorRampShader.ColorRampItem(-limit, QColor(103, 0, 31), f"{-limit:g} dB darker"),
        QgsColorRampShader.ColorRampItem(-limit / 2, QColor(214, 96, 77), ""),
        QgsColorRampShader.ColorRampItem(0, QColor(247, 247, 247), "0"),
        QgsColorRampShader.ColorRampItem(limit / 2, QColor(67, 147, 195), ""),
        QgsColorRampShader.ColorRampItem(limit, QColor(5, 48, 97), f"+{limit:g} dB brighter"),
    ])
    shader.setClip(False)
    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(shader)
    layer.setRenderer(QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, raster_shader))


def rgb(layer):
    provider = layer.dataProvider()
    renderer = QgsMultiBandColorRenderer(provider, 1, 2, 3)
    renderer.setRedContrastEnhancement(contrast(provider, 1, 1, 255))
    renderer.setGreenContrastEnhancement(contrast(provider, 2, 1, 255))
    renderer.setBlueContrastEnhancement(contrast(provider, 3, 1, 255))
    layer.setRenderer(renderer)


def mask(layer):
    classes = [QgsPalettedRasterRenderer.Class(1, QColor(255, 0, 255), "layover"),
               QgsPalettedRasterRenderer.Class(2, QColor(0, 0, 0), "shadow"),
               QgsPalettedRasterRenderer.Class(3, QColor(255, 140, 0), "layover + shadow")]
    layer.setRenderer(QgsPalettedRasterRenderer(layer.dataProvider(), 1, classes))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    src = ROOT / "outputs/qgis" / args.run_id
    report = json.loads((src / "export_report.json").read_text(encoding="utf-8"))
    files = set(report["files"])
    run_report = json.loads((ROOT / "outputs/snap_runs" / args.run_id / "run_report.json").read_text(encoding="utf-8"))
    role_label = {}
    for role, record in run_report["scenes"].items():
        stamp = record["product_id"].split("_")[4]  # sensing start, UTC
        role_label[role] = f"{role.title()} {stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} UTC"
    set_name = run_report.get("scene_set", "ro005")

    app = QgsApplication([], False)
    app.initQgis()
    project = QgsProject.instance()
    project.clear()
    crs = QgsCoordinateReferenceSystem("EPSG:32614")
    project.setCrs(crs)
    project.setTitle(f"TX Hill Country flood - SNAP {args.run_id}, {set_name} (exploratory)")
    root = project.layerTreeRoot()

    def add(layer, group, visible=True, identifiable=True):
        if not identifiable:  # keep Identify clicks for the review layers and rasters
            layer.setFlags(layer.flags() & ~QgsMapLayer.Identifiable)
        project.addMapLayer(layer, False)
        group.addLayer(layer).setItemVisibilityChecked(visible)
        return layer

    review = root.addGroup("Review hotspots (exploratory) - use Identify (Ctrl+Shift+I)")
    context_file = src / "hotspots_context_boxes.geojson"
    if context_file.is_file():
        # boxes carry exact distances to the Guadalupe / named streams, nearest stream name, land cover
        for subset, label, colour, visible in (
            ('"cross_track_agree" = 1 AND "context_group" = \'corridor, land\'', "Both tracks - corridor LAND (best candidates)", "255,0,0", True),
            ('"cross_track_agree" = 1 AND "context_group" <> \'corridor, land\'', "Both tracks - water / off corridor", "0,255,255", True),
            ('"cross_track_agree" = 0', "This track only (likely noise)", "255,0,255", False),
        ):
            layer = QgsVectorLayer(str(context_file), label, "ogr")
            layer.setSubsetString(subset)
            layer.renderer().setSymbol(QgsFillSymbol.createSimple(
                {"color": "0,0,0,0", "outline_color": colour, "outline_width": "1.0"}))
            layer.setDisplayExpression("\"context_group\" || ': ' || \"dist_guadalupe_m\" || ' m to Guadalupe'")
            add(layer, review, visible)
    else:
        for filename, label, colour, visible in (
            ("hotspots_cross_track.geojson", "Darkening flagged on BOTH tracks", "0,255,255", True),
            ("vh_darkening_hotspots.geojson", "Darkening, top 15 this track", "255,0,255", False),
        ):
            if (src / filename).is_file():
                layer = QgsVectorLayer(str(src / filename), label, "ogr")
                layer.renderer().setSymbol(QgsFillSymbol.createSimple(
                    {"color": "0,0,0,0", "outline_color": colour, "outline_width": "0.9"}))
                add(layer, review, visible)

    hydro = root.addGroup("Hydrography (USGS NHD HR)")
    hydro_dir = ROOT / "data/interim/reference"
    for filename, label, style, subset, visible in (
        ("nhd_flowlines_aoi.geojson", "Named streams", {"line_color": "30,120,255", "line_width": "0.5"},
         "\"gnis_name\" IS NOT NULL", True),
        ("nhd_flowlines_aoi.geojson", "All flowlines", {"line_color": "120,170,255", "line_width": "0.2"}, None, False),
        ("nhd_waterbodies_aoi.geojson", "Waterbodies", None, None, True),
    ):
        if not (hydro_dir / filename).is_file():
            continue
        layer = QgsVectorLayer(str(hydro_dir / filename), label, "ogr")
        if subset:
            layer.setSubsetString(subset)
        if style:
            layer.renderer().setSymbol(QgsLineSymbol.createSimple(style))
        else:
            layer.renderer().setSymbol(QgsFillSymbol.createSimple(
                {"color": "0,0,0,0", "outline_color": "0,90,200", "outline_width": "0.4"}))
        add(layer, hydro, visible)

    change = root.addGroup("Change (VH)")
    for a, b, visible in (("pre", "post", True), ("control", "pre", False)):
        if f"rgb_VH_{a}_{b}.tif" in files:
            layer = raster(src / f"rgb_VH_{a}_{b}.tif", f"RGB VH {a}/{b}/{b}  (red = darker after)")
            rgb(layer)
            add(layer, change, visible)
        if f"change_VH_{a}_to_{b}_dB.tif" in files:
            layer = raster(src / f"change_VH_{a}_to_{b}_dB.tif", f"VH change {a} -> {b} (dB)")
            diverging(layer)
            add(layer, change, False)

    backscatter = root.addGroup("Backscatter (dB)")
    for role in ("post", "pre", "control"):
        for pol in ("VH", "VV"):
            name = f"{role}_Sigma0_{pol}_dB.tif"
            if name in files:
                layer = raster(src / name, f"{role_label[role]} Sigma0 {pol} dB")
                grey(layer, *STRETCH_DB[pol])
                add(layer, backscatter, False)
    backscatter.setExpanded(False)

    terrain = root.addGroup("Terrain (pre geometry)")
    layer = raster(src / "pre_layoverShadowMask.tif", "Layover / shadow")
    mask(layer)
    add(layer, terrain, False)
    layer = raster(src / "pre_localIncidenceAngle.tif", "Local incidence angle (deg)")
    grey(layer, 20, 70)
    add(layer, terrain, False)
    terrain.setExpanded(False)

    # Post-event aerial imagery, streamed (not downloaded) from the registered NOAA NGS ERI service index.
    eri_index = ROOT / "data/raw/reference/noaa_ngs/eri_2025_services_index.json"
    if eri_index.is_file():
        summary = json.loads((ROOT / "docs/acquisition/aoi_summary.json").read_text(encoding="utf-8"))
        w, s, e, n = summary["bounds_wgs84"]
        flights = [f for f in json.loads(eri_index.read_text(encoding="utf-8"))
                   if f["name"].startswith("202507") and not (f["bounds"][2] < w or f["bounds"][0] > e
                                                              or f["bounds"][3] < s or f["bounds"][1] > n)]
        eri = root.addGroup("Post-event aerial: NOAA NGS ERI (July 2025)")
        for f in sorted(flights, key=lambda f: f["name"]):
            date = f"{f['name'][:4]}-{f['name'][4:6]}-{f['name'][6:8]}"
            note = {"20250711": "1 day after RO107 post", "20250712": "2 days after RO107 post"}.get(f["name"][:8], "")
            if f["name"] >= "20250713":
                note = "after 13-15 Jul second pulse"
            label = f"{date} {f['attribution']} ({f['name'][8:].lstrip('_')})" + (f" - {note}" if note else "")
            layer = QgsRasterLayer(f"type=xyz&url={f['tiles'][0]}&zmin={f['minzoom']}&zmax={f['maxzoom']}", label, "wms")
            layer.setAttribution(f"{f['attribution']} via NOAA NGS Emergency Response Imagery")
            add(layer, eri, f["name"][:8] in ("20250711", "20250712"), identifiable=False)

    context = root.addGroup("AOI")
    aoi = QgsVectorLayer(str(ROOT / "data/interim/boundaries/aoi_provisional.geojson"), "AOI (provisional, Kerr + 10 km)", "ogr")
    aoi.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "255,215,0", "outline_width": "0.8"}))
    add(aoi, context, identifiable=False)

    basemaps = root.addGroup("Basemaps")
    for name, url, visible in (
        ("Esri World Imagery (Feb 2024 here, PRE-event)", "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", False),
        ("OpenStreetMap", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", True),
    ):
        add(QgsRasterLayer(f"type=xyz&url={url}&zmin=0&zmax=19", name, "wms"), basemaps, visible, identifiable=False)

    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(
        project.mapLayersByName("RGB VH pre/post/post  (red = darker after)")[0].extent(), crs))
    out = ROOT / "qgis" / f"{args.run_id}.qgz"
    if not project.write(str(out)):
        raise RuntimeError(f"Failed to write {out}")
    print(f"wrote {out.relative_to(ROOT)}")
    app.exitQgis()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
