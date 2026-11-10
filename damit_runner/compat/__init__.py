"""Compatibility shims for damsuite/DamSafety imports that DWR Runner core modules use.

DamIT Runner ports core/ modules from DamSafety Runner. Those modules import from
``..damsuite`` (the shared DamSafety package). This package provides the equivalents
for DamIT, backed by damit_core where possible and thin implementations otherwise.
"""
