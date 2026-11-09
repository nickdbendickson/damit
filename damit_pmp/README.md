# DamIT PMP 0.1.0 – NOAA Atlas 14 only

Processing provider `damit_pmp`. Depends on DamIT Core. **The only data source is NOAA Atlas 14**,
read from the NOAA/NWS Precipitation Frequency Data Server (PFDS, https://hdsc.nws.noaa.gov/pfds/), or
from an Atlas 14 GIS grid you downloaded from PFDS.

This is not a port of DamSafety PMP (the internal prototype of the North Dakota statewide PMP
Evaluation Tool). It ships none of that tool's code or data, uses no PMP study geodatabase, no HMR / HMS
or state PMP product and no other precipitation source. Atlas 14 publishes precipitation-frequency
estimates up to the 1000-year ARI; **0.1.0 computes no probable maximum precipitation**.

| Tool | What it does |
|---|---|
| `damit_pmp:pointpf` | PFDS point query: 19 durations (5 min – 60 days) × PDS 1 – 1000-year ARI (or AMS 1/2 – 1/1000 AEP), depth or intensity, English or metric, with 90% bounds. Writes a CSV table and a JSON file with the Atlas 14 volume, version, region, query URL, fetch time and citation. |
| `damit_pmp:basinpf` | The same at a point on the basin plus evenly spread points inside it (MAX_POINTS, default 9), combined cell by cell (mean or max); a sample-point layer. No areal reduction (Atlas 14 values are point values). |
| `damit_pmp:hyetograph` | Alternating-block design hyetograph from a pointpf / basinpf JSON: storm total = the Atlas 14 depth for the storm duration (1 h – 10 days) at the chosen frequency; sub-durations log-log interpolated between published durations. Not an Atlas 14 temporal distribution. |
| `damit_pmp:gridbasin` | Basin mean / min / max of a local Atlas 14 GIS grid (values in thousandths of an inch, SCALE 0.001); frequency and duration read from the standard file name (e.g. `mw100yr24ha.asc`). |

A location outside Atlas 14 coverage (for example Portland, Oregon, checked 2026-11-09) fails with
"NOAA Atlas 14 does not cover this location (PFDS: …)". PFDS answers are cached (CACHE_DIR, else the
DamIT `pfds_cache` setting, else next to the outputs); OFFLINE uses the cache only; basin queries wait
one second between live requests.

Citation form written to every output: *<authors>, NOAA Atlas 14 Volume <v> Version <x>,
Precipitation-Frequency Atlas of the United States, <region>. NOAA, National Weather Service, Silver
Spring, MD.*

Tests use three recorded PFDS answers (`tests/fixtures/`: Fargo ND PDS English, Lincoln NE AMS metric,
Portland OR outside coverage); no test calls NOAA.
