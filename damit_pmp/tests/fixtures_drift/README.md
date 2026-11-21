# fixtures_drift/ — deliberate near-miss PFDS answers

Each file mutates ONE thing about the known-good Fargo PDS capture
(`../fixtures/pfds_pds_english_fargo_nd.txt`, the real PFDS answer NOAA serves for
Fargo ND) so that a NOAA redesign of the PFDS page fails the suite loudly instead of
silently feeding garbage rain depths to the PMP tools.

| File | Drift simulated | Expected outcome |
|---|---|---|
| `pfds_html_error_page.html` | an HTML 503 page where JSON was asked for (has happened) | `Atlas14Error`, not a number anywhere |
| `pfds_renamed_quantiles.txt` | the `quantiles` variable renamed (page redesign) | `Atlas14Error` about durations x frequencies |
| `pfds_row_dropped.txt` | one duration row missing (dims 18 x 10, not 19 x 10) | `Atlas14Error` with both dims in the message |
| `pfds_error_msg_refusal.txt` | an `ErrorMsg` refusal that is not the `'none'` coverage answer | `Atlas14Error` carrying NOAA's own message |
| `pfds_nonnumeric_cell.txt` | a non-numeric cell in the quantiles array | `Atlas14Error` "cannot read quantiles" |

All five are exercised by `tests/test_pfds_schema.py`. The known-good contract itself
(dims 19 x 10 for PDS, 19 x 9 for AMS, the scalar metadata fields, CoverageError for
`result = 'none'`) is asserted in `tests/test_atlas14.py` against the real captures in
`fixtures/`.

Derived 2026-11-20 from the Fargo capture; no live network needed to maintain them.
