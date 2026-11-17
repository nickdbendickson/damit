"""What differs between DamIT Finder and DamSafety Finder: names, the Processing provider id and
the hints about which layers to give. Every other file of the Finder is the same in both
repositories (damit_finder/ here, the DamSafety Finder folder in dAmIt_Plugins) except the
docstring of core/warp_opts.py."""
from .provider import PROVIDER_ID  # noqa: F401  (the one place the id is written)

NAME = "DamIT Finder"
KNOWN_EXAMPLES = ("the NID (USACE National Inventory of Dams), your state's dam and pond lists; for "
                  "crossings NBI bridges (DamIT Data downloads them; item 43B 19 = culvert), state DOT "
                  "culvert inventories, USGS stream crossings, SARP / ABI crossings")
EMB_HELP = ("Layers: a bare-earth DEM (USGS 3DEP 1 m or 1/3 arc-second, a file or a VRT); 3DHP / NHD "
            "flowlines; roads (TIGER / OSM / HPMS from DamIT Data) and railroads. Output: "
            "'embankments' (every fill, status listed / unsure / new against the known structures), "
            "'screening_dams' (the fills that hold water and are not listed, status 'Candidate') and a "
            "review hillshade lit from all round. A candidate has no NID ID: DamIT Screener refuses it "
            "as a dam record (the NID-only rule) until the state or the NID lists it - report the new "
            "ones to the state dam-safety office.")
POND_HELP = ("The pond engine is the suite's screening pond engine (core/ponds.py). Every pond is "
             "checked against the known structures: 'screening_ponds' holds the not-listed ponds that "
             "could release water.")
CROSS_HELP = ("Known structures for crossings: NBI bridges (DamIT Data), state DOT culvert "
              "inventories, USGS stream crossings, SARP / ABI road crossings.")
# Image services with a near-infrared band for the water outlines: (label, ImageServer address,
# green band, near-infrared band). USGS NAIP Plus is red, green, blue, near-infrared (the most
# recent NAIP of each place, 60 cm or finer). A state's own 4-band or colour-infrared service
# goes in as an address: check its band order (the service's keyProperties). A classic
# colour-infrared composite is NIR, red, green (green 3, NIR 1), but some state services are NIR,
# green, blue (North Dakota's GIS Hub: green 2, NIR 1).
IMAGE_SERVICES = [
    ("USGS NAIP Plus (the most recent NAIP; 4-band)",
     "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer", 2, 4),
]
# 'Add evidence to fills': the default imagery for the water history, one per line (YEAR | source |
# bands). USGS NAIP Plus is only the most recent NAIP of each place; for a history give your state's
# yearly 4-band or colour-infrared NAIP services or files (check each service's band order: a classic
# colour-infrared composite is nir=1 red=2 green=3; North Dakota's GIS Hub CIR years are nir=1 green=2).
EVIDENCE_IMAGES = ("0 | https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer | "
                   "red=1 green=2 blue=3 nir=4")
EVIDENCE_IMAGES_HELP = ("The default is USGS NAIP Plus, the most recent NAIP only (year shown as 0): add "
                        "one line per older NAIP year your state serves for a water history.")
WATER_HELP = ("Layers: 3DHP / NHD waterbodies or the NWI as the mapped water bodies. The 'water' "
              "polygons with mapped = no are the ponds no layer has: give them to 'Find ponds and "
              "dugouts' as its water bodies to ask the LiDAR whether each is held above the ground.")
# Build-the-water-mosaic tool: the output CRS of the per-tile count / elevation rasters. DamIT
# builds for the whole U.S. (EPSG:5070, CONUS Albers), so tiles from any state land on one grid;
# DamSafety builds for North Dakota (EPSG:26914).
MOSAIC_EPSG = 5070
MOSAIC_REGION = "the whole U.S. (CONUS Albers)"
MOSAIC_HELP = ("Point it at a folder of classified LiDAR tiles (USGS 3DEP .las/.laz) and it writes "
               "the water_count.vrt and water_elev.vrt that 'Find open water' reads with its "
               "'Prebuilt class-9 water-count raster' input. Build it once per area; the open-water "
               "tool then reads the mosaic a tile at a time, so a county or a whole state is in "
               "reach without re-reading the raw point cloud. Tiles whose CRS is not in the file "
               "need their EPSG. Dry land and the gaps between tiles read back as no water.")
OSM_HELP = ("Use a Geofabrik extract of your state (https://download.geofabrik.de, <state>-latest.osm.pbf). "
            "Give the output to the other tools as a known-structure layer.")
# The starter fill score model shipped with the plugin (core/score.py; the same file as DamSafety
# Finder's default). It was learned from listed dams on USGS 1 m LiDAR in 7 North Dakota regions
# and, with nothing from Iowa in it, ranked the fills on 15 Iowa 1 m tiles against Iowa's pond-dam
# census with AUC 0.89. The Find fills tool uses it when no other model is given: a starting
# point, not a model of your state. Relearn it with the score tool where you have a dam list.
DEFAULT_MODEL = "models/nd_fill_score_trees_2026-11.json"
# Shown at the end of the review batch tool's help (EVIDENCE on): with the default image list a
# card has one look at the most recent image, not a water history.
CARD_IMAGES_HELP = ("With the default image list a card reads '1 of 1' or '0 of 1': one look at the most recent "
                    "image, not a water history. To see water year after year, list your state's yearly images "
                    "with a near-infrared band in IMAGES, one per line.")
