# Sites and map

The **Sites** page holds the project's monitoring sites, their sensors and datasets, and its zones (sewersheds,
drainage areas): a tree on the left, a **Map** and a **Time series** tab in the middle, and the **Properties** of the
selection on the right. A selection made in the tree, on the map or elsewhere is one selection everywhere.

```{image} ../_static/screenshots/sites-map.png
:alt: Sites page: tree of sites and zones, map with a sewershed and two sites, properties of the selected site.
:class: screenshot
```

## Importing data

**Import data** (<kbd>F5</kbd>) reads a CSV (any column names, mapped in the dialog) or FlowFinity rain and flow
`.tsf` files into a new site or an existing one, with the flow units converted. The series are stored in the
project; the original files are no longer needed.

## Properties and attributes

The property editor shows a site's or zone's name, description, identifiers, location and attributes with their
units and limits; values outside the limits are refused. **Add attribute...** defines a new attribute (name, type,
unit, limits, description) for sites or zones. Assess needs two of them for an official grade: *Average dry weather
flow (ODWF-A)* and *Sewer system*.

## Map tools

On the Map tab the toolbar's chart buttons act on the map, and the page adds its own tools; exactly one is active:

| Tool | Use |
| --- | --- |
| **Select** (<kbd>S</kbd>) | Click a site or zone; <kbd>Ctrl</kbd>+click adds or removes; drag a rectangle - or, from the button's arrow, draw a free **lasso** - to select what is inside. Sites win over the zones under them; hold <kbd>Alt</kbd> to pick zones only. <kbd>Esc</kbd> clears the selection. |
| **Pan**, **Zoom box** | As on the charts. |
| **Edit locations** | Drag a site to move it; click the map to place the selected site. |
| **Draw zone** | Click the vertices, double-click or <kbd>Enter</kbd> to finish, <kbd>Esc</kbd> to cancel. |

**Fit all** shows every located feature and **Zoom to selection** the selected ones. The status bar gives the
latitude and longitude under the mouse.

The map has no background by default. **Basemap** adds OpenStreetMap tiles after asking once, because the tile
server then sees the area you view (never your project data); tiles are cached on the computer.

## GIS import and export

**Import GIS layer...** reads sewersheds (polygons) or sites (points) from a file geodatabase (choose the layer), a
shapefile, GeoPackage, GeoJSON, KML/KMZ or any other format GDAL reads, and converts the coordinates to longitude and
latitude. The dialog previews the layer on a map and lets you choose:

- the column with each feature's **name**, and the column with its **identifier** (kept as an alternative id and used
  to recognise features already in the project);
- the **zone kind** (sewershed, drainage area, ...), fixed or from a column;
- which **columns become attributes**, with their name, type and unit;
- what to do with features already in the project: **skip**, **update** their geometry and attributes, or **add**
  them again.

Polygons and multipolygons (holes included) become zones, points become sites; line layers are refused with the
reason. Each site inside a zone is linked to it, and each zone's area on the WGS84 ellipsoid is stored as
*Contributing area* (acres).

**Export to GIS...** writes the zones or the sites (the selected ones, or all) with their attributes to a
GeoPackage, GeoJSON or shapefile. GIS import and export need the `gis` extra (included in the Windows installer).

## Calibration and validation periods

On the **Time series** tab, **Select calibration** (<kbd>C</kbd>) and **Select validation** (<kbd>V</kbd>) turn the
next drag into a period; the shaded period can then be moved or resized. **Zoom to** a period, **Visible →
calibration** and **Clear period** are on the toolbar too. Without a period the whole record is used.

```{image} ../_static/screenshots/sites-timeseries.png
:alt: Time series with rain above flow and the calibration and validation periods shaded.
:class: screenshot
```
