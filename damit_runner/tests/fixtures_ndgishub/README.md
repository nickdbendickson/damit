Golden answers from the ND GIS Hub ArcGIS REST services (ndgishub.nd.gov), captured for
the schema-drift tests in test_ndgishub_wire.py, audit 2026-11-20.

The load-bearing contract the Runner depends on: Imagery/Dates_Imagery layer 41's
/query answer carries per-seamline flight dates in the IDATE attribute field
(parse_date accepts 'YYYY-MM-DD', 'M/D/YYYY' and 'YYYYMMDD'; imagery_dates dedups and
sorts them). Any redesign of the layer number, field name or answer shape must fail
these tests loudly rather than quietly turning every QA map's flight-date line into
"imagery date unknown".

Captured 2026-11-20 from the live service (all public data, no auth).
