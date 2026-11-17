"""TRUE_HOLE and oversize-component masks for NoData cells in a depth grid.

Shared by DamIT Hazard, DamIT Runner and Heim (one implementation). No QGIS.

Named criterion TRUE_HOLE (also recorded as nodata_true_hole):

  The wet footprint is every cell with a finite depth strictly greater than 0.
  Non-wet cells (NoData, or any finite depth <= 0) are grouped with
  TRUE_HOLE_CONNECTIVITY = 4 (cardinal neighbours only). A NoData cell is a
  true hole when its 4-connected non-wet component does not touch the raster
  border (it is enclosed by the wet footprint) AND that component has at most
  TRUE_HOLE_MAX_CELLS cells.

  4-connectivity is used on purpose. A path that reaches the border only
  through a corner (diagonal) does not connect a pocket to the exterior, so
  that pocket is enclosed. Water that touches only at a corner is not treated
  as an outlet.

  TRUE_HOLE_MAX_CELLS (25, a 5x5 block) is the named size cap. A larger
  enclosed component is not a hole: it is a dry island or cut-off area
  (flag nodata_oversize_component) and scores dry. Finite-0 cells take part
  in connectivity and in the size count, but are never themselves holes
  (already dry).

The Runner writes every dry cell as NoData, so an enclosed NoData pocket on
Runner output is often model-dry high ground, not a gap in the results.
Scoring of those cells is done by the caller (WSE-consistent neighbourhood
depth on a grid coarser than 20 m; never raw neighbour depth).
"""
from collections import deque

import numpy as np

# Cardinal neighbours only (see module docstring).
TRUE_HOLE_CONNECTIVITY = 4
# Named size cap: a 5x5 block. Large enough for a small cluster of missing
# cells, including the 15-cell knoll on DWR-2659. A 52x52 island (2,704 cells)
# is over the cap, so its rim is not treated as a hole.
TRUE_HOLE_MAX_CELLS = 25
_CARDINAL = ((-1, 0), (1, 0), (0, -1), (0, 1))


def analyze_nodata(depth, max_cells=TRUE_HOLE_MAX_CELLS, cache=False):
    """Masks and component sizes for a 2-d depth array (NaN = NoData).

    Returns a dict:
      hole      bool mask of TRUE_HOLE NoData cells (enclosed, size <= cap)
      oversize  bool mask of enclosed NoData cells in a component larger than
                the cap
      enclosed  bool mask of enclosed NoData cells (any size)
      size      int array, 4-connected non-wet component size (0 if wet)
      max_cells the cap used
    Cached on the array when cache=True so a classify / impacts pass does not
    rebuild the masks on every receptor.
    """
    a = np.asarray(depth)
    cap = int(max_cells)
    if cache:
        hit = getattr(a, "_damit_true_hole", None)
        if (isinstance(hit, dict) and hit.get("max_cells") == cap
                and hit.get("shape") == a.shape and hit.get("result") is not None):
            return hit["result"]
    result = _analyze(a, cap)
    if cache:
        try:
            a._damit_true_hole = {"max_cells": cap, "shape": a.shape, "result": result}
        except (AttributeError, TypeError):
            pass
    return result


def _analyze(a, cap):
    empty = {
        "hole": np.zeros(getattr(a, "shape", (0,)), dtype=bool),
        "oversize": np.zeros(getattr(a, "shape", (0,)), dtype=bool),
        "enclosed": np.zeros(getattr(a, "shape", (0,)), dtype=bool),
        "size": np.zeros(getattr(a, "shape", (0,)), dtype=np.int32),
        "max_cells": int(cap),
    }
    if a.ndim != 2 or a.size == 0:
        return empty
    wet = np.isfinite(a) & (a > 0)
    nodata = ~np.isfinite(a)
    nonwet = ~wet
    nr, nc = a.shape
    exterior = np.zeros((nr, nc), dtype=bool)
    q = deque()

    def seed(r, c):
        if nonwet[r, c] and not exterior[r, c]:
            exterior[r, c] = True
            q.append((r, c))

    for c in range(nc):
        seed(0, c)
        if nr > 1:
            seed(nr - 1, c)
    for r in range(nr):
        seed(r, 0)
        if nc > 1:
            seed(r, nc - 1)
    while q:
        r, c = q.popleft()
        for dr, dc in _CARDINAL:
            rr, cc = r + dr, c + dc
            if 0 <= rr < nr and 0 <= cc < nc and nonwet[rr, cc] and not exterior[rr, cc]:
                exterior[rr, cc] = True
                q.append((rr, cc))

    enclosed_nonwet = nonwet & ~exterior
    size = np.zeros((nr, nc), dtype=np.int32)
    seen = np.zeros((nr, nc), dtype=bool)
    for r0 in range(nr):
        for c0 in range(nc):
            if not enclosed_nonwet[r0, c0] or seen[r0, c0]:
                continue
            cells = []
            q.append((r0, c0))
            seen[r0, c0] = True
            while q:
                r, c = q.popleft()
                cells.append((r, c))
                for dr, dc in _CARDINAL:
                    rr, cc = r + dr, c + dc
                    if (0 <= rr < nr and 0 <= cc < nc and enclosed_nonwet[rr, cc]
                            and not seen[rr, cc]):
                        seen[rr, cc] = True
                        q.append((rr, cc))
            n = len(cells)
            for r, c in cells:
                size[r, c] = n
    enclosed = nodata & enclosed_nonwet
    hole = enclosed & (size <= cap) & (size > 0)
    oversize = enclosed & (size > cap)
    return {"hole": hole, "oversize": oversize, "enclosed": enclosed,
            "size": size, "max_cells": int(cap)}


def true_hole_mask_from_array(depth, max_cells=TRUE_HOLE_MAX_CELLS, cache=True):
    """Boolean mask of TRUE_HOLE NoData cells (enclosed, component size <= cap)."""
    return analyze_nodata(depth, max_cells=max_cells, cache=cache)["hole"]


def oversize_mask_from_array(depth, max_cells=TRUE_HOLE_MAX_CELLS, cache=True):
    """Boolean mask of enclosed NoData cells in a component larger than the cap."""
    return analyze_nodata(depth, max_cells=max_cells, cache=cache)["oversize"]
