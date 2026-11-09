# PFDS fixtures

Verbatim answers of the NOAA Atlas 14 Precipitation Frequency Data Server
(`https://hdsc.nws.noaa.gov/cgi-bin/new/cgi_readH5.py`), fetched once on 2026-11-09 so the tests
never call NOAA:

| File | Query |
|---|---|
| `pfds_pds_english_fargo_nd.txt` | lat=46.8772 lon=-96.7898 type=pf data=depth units=english series=pds (Volume 8 v2, Midwestern States) |
| `pfds_ams_metric_lincoln_ne.txt` | lat=40.8136 lon=-96.7026 type=pf data=depth units=metric series=ams |
| `pfds_no_coverage_portland_or.txt` | lat=45.52 lon=-122.68 (Oregon is outside NOAA Atlas 14; PFDS answers result = 'none') |
