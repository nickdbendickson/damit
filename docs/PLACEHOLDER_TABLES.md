# Placeholder tables (B2)

Read 2026-11-23. No number in `damit_runner/core/consequences.py` or `damit_runner/core/probabilistic.py` was changed. The headers that call the tables placeholders are unchanged. Computed results do not move.

The same tables are in the DamSafety Runner. This note is the record to port back.

## Fatality rates

Source read: Wayne J. Graham, *A Procedure for Estimating Loss of Life Caused by Dam Failure*, U.S. Bureau of Reclamation DSO-99-06, September 1999, Table 7, "Recommended Fatality Rates for Estimating Loss of Life Resulting from Dam Failure", printed page 38 (PDF page 41 of https://www.usbr.gov/damsafety/TechDev/DSOTechDev/DSO-99-06.pdf). Text extracted with pypdf from that file. Suggested rate, not the suggested range:

| Flood severity | Warning | Understanding | Suggested rate |
| --- | --- | --- | --- |
| HIGH | no warning | not applicable | 0.75 |
| HIGH | 15 to 60, and more than 60 | vague and precise | no rate printed. The cell says to use the value above on the people who remain in the floodplain, and that no guidance is given on how many remain |
| MEDIUM | no warning | not applicable | 0.15 |
| MEDIUM | 15 to 60 | vague / precise | 0.04 / 0.02 |
| MEDIUM | more than 60 | vague / precise | 0.03 / 0.01 |
| LOW | no warning | not applicable | 0.01 |
| LOW | 15 to 60 | vague / precise | 0.007 / 0.002 |
| LOW | more than 60 | vague / precise | 0.0003 / 0.0002 |

`DEFAULT_FATALITY_TABLE` has no understanding column. "none" and "short" are both the no-warning column. "some" is 15 to 60 minutes. "adequate" is more than 60 minutes. Where the coded rate equals Table 7's vague-understanding suggested rate, that is noted. The precise-understanding rate is a different number and was not substituted, because the module cannot say which understanding applies. The two HIGH-with-warning cells are not in Table 7 and were not filled.

| Coded cell | Value left in place | Table 7 |
| --- | --- | --- |
| low, none and short | 0.01 | matches LOW, no warning, 0.01 |
| low, some | 0.007 | matches LOW, 15 to 60, vague 0.007 (precise is 0.002) |
| low, adequate | 0.0003 | matches LOW, more than 60, vague 0.0003 (precise is 0.0002) |
| medium, none and short | 0.15 | matches MEDIUM, no warning, 0.15 |
| medium, some | 0.04 | matches MEDIUM, 15 to 60, vague 0.04 (precise is 0.02) |
| medium, adequate | 0.03 | matches MEDIUM, more than 60, vague 0.03 (precise is 0.01) |
| high, none and short | 0.75 | matches HIGH, no warning, 0.75 |
| high, some | 0.15 | not replaced: Table 7 prints no rate |
| high, adequate | 0.04 | not replaced: Table 7 prints no rate |

Reclamation's later RCEM (2015) draws fatality rate against warning time instead of this table. That document was not used to change a number.

## Depth-damage curves

`GENERIC_CURVES` and the first-floor heights (`FFH_BY_OCCUPANCY_FT`, `FFH_BY_FOUNDATION_FT`) are labeled generic placeholders in the module. No USACE depth-damage curve was opened here, so none of these values was replaced.

Depths, feet: 0, 1, 2, 4, 6, 8, 12.

| Occupancy | structure percent | contents percent |
| --- | --- | --- |
| residential | 0, 15, 25, 40, 55, 70, 90 | 0, 10, 25, 45, 60, 75, 90 |
| commercial | 0, 10, 20, 35, 50, 60, 80 | 0, 15, 30, 50, 70, 85, 100 |
| industrial | 0, 8, 15, 30, 45, 55, 75 | 0, 10, 25, 45, 65, 80, 95 |
| public | 0, 10, 20, 35, 50, 60, 80 | 0, 10, 20, 40, 60, 75, 90 |
| agricultural | 0, 5, 10, 20, 30, 40, 60 | 0, 10, 20, 40, 60, 80, 100 |
| other | 0, 10, 20, 35, 50, 60, 80 | 0, 15, 30, 50, 70, 85, 100 |

## Destruction and severity thresholds

Left as coded. Not replaced.

| Parameter | Value left in place | Why it was not replaced |
| --- | --- | --- |
| destroy_dv_ft2s | 75 | The module calls this a recollection. No source with that depth-times-velocity threshold was read. DSO-99-06's DV is discharge over a width term, not depth times velocity, so its "50" is not this 75. |
| destroy_depth_ft | 20 | No source read. |
| sev_med_depth_ft / sev_med_dv_ft2s | 3 / 7 | No source read. Not the DSO-99-06 severity categories. |
| sev_high_depth_ft / sev_high_dv_ft2s | 20 / 75 | No source read. |
| par_depth_ft | 0.5 | No source read. |
| warning_edges_min | 15, 60 | These match the Table 7 warning bins (under 15, 15 to 60, more than 60). Left as coded; not newly copied from the table. |

## Breach-parameter distributions

`default_width` is triangular 0.5, 1.0, 1.5. `default_time` is triangular 0.5, 1.0, 2.0. `default_manning` is triangular 0.75, 1.0, 1.3. `DEFAULTS_NOTE` already says these are not published values.

Not replaced. Froehlich, "Embankment Dam Breach Parameters and Their Uncertainties", Journal of Hydraulic Engineering 134(12), 1708-1721 (2008), was not opened (the ASCE copy is not available here). Wahl, "Uncertainty of Predictions of Embankment Dam Breach Parameters", Journal of Hydraulic Engineering 130(5) (2004), was not opened. No prediction interval was copied in from memory.
