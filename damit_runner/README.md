# DamIT Runner

Processing provider `damit_run`. The breach run the Screener hands off is `damit_run:rundam`. LISFLOOD-FP stays the default flood engine.

0.9.2 adds the DamSafety Runner tool wrappers that are not North Dakota-specific: `probabilistic`, `nested`, `consequences` (placeholder tables; they do not classify), `animation`, `hecrasimport`, `submittal`, `verification`, `validationrecord`, `verifymanifest`, `selftest`, `fillgaps`, `nlcdmanning`, `conditiondem`, `benchmark`, `hazardhandoff` (calls `damit:classify`), `products`, `culvertprep`, `rainfallrunoff` (storm depth from DamIT PMP or the engineer), `spillwayadequacy` (residual freeboard is an input) and `chainbatch` (Screener, Runner, HEC-RAS export, `damit:rasimport`, `damit:classify`).

The statewide LiDAR mosaic and the ND hand-off are not included. `damit:rasimport` is added with the Hazard tools. None of these change an existing `rundam` result unless you run them.

The algorithm list is also in [docs/REFERENCE.md](../docs/REFERENCE.md).
