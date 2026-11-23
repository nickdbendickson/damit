# Known-class benchmark

`dams.json` is the official list. It is empty on purpose. Add a dam only when both of these exist:

- an official class cited to the National Inventory of Dams or the state record (a link or a document), and
- receptors (a small JSON fixture) or rasters under the folder in `DAMIT_CLASS_BENCHMARK_DATA`.

Do not guess a class. Lake Delhi and Edenville stay out until those inputs are in that folder.

```
python3 scripts/run_class_benchmark.py
python3 scripts/run_class_benchmark.py --dams tests/class_benchmark/fixtures/lower_probe.json
```

The table is official class, DamIT class, and agree / higher / LOWER. Exit status is 1 when any row is LOWER. A missing raster is skipped, not treated as a lower class. Each preset prints its `status` and `verification` from `damit_catalog/data/presets.json`.
