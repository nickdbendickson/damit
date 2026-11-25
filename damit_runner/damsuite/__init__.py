"""The one name the vendored Boann reaches outside itself for (DamIT Runner 0.11.0).

damit_runner/boann/grid/condition.py, byte-identical with DamSafety Core's, imports
`from ...damsuite import gdalsafe` (in DamSafety that is DamSafety_Core.damsuite). From
damit_runner/boann/grid that resolves to this package, whose gdalsafe is the Runner's own
compat/gdalsafe.py. Nothing else lives here."""
