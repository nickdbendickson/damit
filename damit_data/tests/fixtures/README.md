# DamIT Data test fixtures

Small offline answers the provider tests feed through `fakehttp.FakeHttp`. No test touches the network.

| File | Shape of | Notes |
|---|---|---|
| `nsi_fargo_tiny.json` | USACE NSI API `?bbox=...&fmt=fc` answer | 3 real structures near Fargo, trimmed |
| `hifld_*_tiny.geojson` | HIFLD FeatureServer `query?f=geojson&outFields=*` answer, one per layer (hospitals, schools, fire stations, EMS) | synthetic names and points; EMS is an empty answer on purpose |
| `nbi_nd_tiny.txt` | FHWA NBI delimited file (`<fips><postal>23.txt`) | synthetic rows, a subset of the NBI item columns, NBI's single-quoted text |

Every fixture stays under a few KB. Add a fixture only with a test that reads it.
