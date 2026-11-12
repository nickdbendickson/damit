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
# goes in as an address (colour-infrared is NIR, red, green: green 3, NIR 1).
IMAGE_SERVICES = [
    ("USGS NAIP Plus (the most recent NAIP; 4-band)",
     "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer", 2, 4),
]
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
