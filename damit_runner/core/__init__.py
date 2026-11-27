"""The Runner's core. Boann (the flood engine and the terrain conditioner) is vendored once, byte-
identical, at damit_runner/boann (pinned by damit_runner/BOANN.lock; core/metalflood and
core/metalterrain here are shims onto it). The two things Boann used to reach up into this folder
for are lent to it here, imported only when used: the sub-grid channel builder (core/sgc on
core/grid, so DamIT's default curve, Bieger 2015, still applies) and the depression-fill oracle
(core/terrain.priority_flood). See damit_runner/boann/hydro/host.py. DamIT Runner 0.11.0, a port of
DamSafety Runner 3.101.1's core/__init__.py."""


def _channel_builder(z, xll, yll, dx, nodata, inflow_rc, channel_n):
    from . import grid as _grid
    from . import sgc as _sgc
    ch = _sgc.build(_grid.Grid(z, xll, yll, dx, nodata), inflow_rc=inflow_rc, channel_n=channel_n)
    return ch.width, ch.depth, ch.start_depth, ch.channel_n


def _priority_flood(dem):
    from .terrain import priority_flood
    return priority_flood(dem)


def _lend_to_boann():
    try:
        from ..boann.hydro import host
    except ImportError:            # core/ loaded outside the plugin package: Boann runs without a host
        return
    host.register("channel_builder", _channel_builder)
    host.register("priority_flood", _priority_flood)


_lend_to_boann()
