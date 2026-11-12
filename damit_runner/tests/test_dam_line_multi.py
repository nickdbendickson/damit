"""Runner 0.3.2: a dam line that is a MultiLineString (DWR-2645 Pheasant Lake). damfolder.read used to skip it without a word,
so the model had no dam line and the toe fell back to 150 m from the inventory point. It now joins the parts end to end, uses
the longest when several remain, and says which part was used and why. No engine runs."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from damit_runner.flood import damfolder as DF  # noqa: E402
from damit_runner.flood import rasters as R  # noqa: E402

LAT = 47.0
DEG_M = 111320.0 * 0.682                      # a degree of longitude in metres at 47 N, about


def feature(geometry):
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": geometry}]}


def multi(*parts):
    return feature({"type": "MultiLineString", "coordinates": [[list(p) for p in part] for part in parts]})


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dl_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def put(self, gj, name="dam_line.geojson"):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as f:
            json.dump(gj, f)
        return os.path.join(self.tmp, name)


class TestPick(unittest.TestCase):
    def test_a_plain_line_is_unchanged_and_has_no_note(self):
        line, note = DF.pick_dam_line([[(0, 47), (0.001, 47)]])
        self.assertEqual(line, [(0.0, 47.0), (0.001, 47.0)])
        self.assertEqual(note, "")

    def test_two_parts_that_meet_are_joined_end_to_end(self):
        line, note = DF.pick_dam_line([[(0, 47), (0.001, 47)], [(0.001, 47), (0.002, 47.0005)]])
        self.assertEqual(line, [(0.0, 47.0), (0.001, 47.0), (0.002, 47.0005)])
        self.assertIn("joined end to end into one line", note)

    def test_a_part_given_backwards_is_joined_too(self):
        line, _ = DF.pick_dam_line([[(0, 47), (0.001, 47)], [(0.002, 47.0005), (0.001, 47)]])
        self.assertEqual(len(line), 3)
        self.assertEqual({line[0], line[-1]}, {(0.0, 47.0), (0.002, 47.0005)})

    def test_three_parts_chain_into_one(self):
        line, _ = DF.pick_dam_line([[(0, 47), (1e-3, 47)], [(2e-3, 47), (3e-3, 47)], [(1e-3, 47), (2e-3, 47)]])
        self.assertIn(line, ([(0.0, 47.0), (1e-3, 47.0), (2e-3, 47.0), (3e-3, 47.0)],
                             [(3e-3, 47.0), (2e-3, 47.0), (1e-3, 47.0), (0.0, 47.0)]))     # direction does not matter

    def test_disjoint_parts_use_the_longest_and_say_so(self):
        short = [(0, 47), (0.0005, 47)]
        long_ = [(0.01, 47.01), (0.012, 47.01), (0.014, 47.011)]
        line, note = DF.pick_dam_line([short, long_])
        self.assertEqual(line, [(0.01, 47.01), (0.012, 47.01), (0.014, 47.011)])
        self.assertIn("the longest was used", note)
        self.assertIn("other part(s) are not used", note)
        self.assertIn("3 vertices", note)

    def test_the_longest_is_by_length_not_by_vertex_count(self):
        many_short = [(0 + i * 1e-5, 47) for i in range(20)]            # 20 vertices, ~ 14 m
        two_far = [(0.01, 47), (0.011, 47)]                              # 2 vertices, ~ 76 m
        line, _ = DF.pick_dam_line([many_short, two_far])
        self.assertEqual(line, [(0.01, 47.0), (0.011, 47.0)])

    def test_projected_metres_work_as_well_as_lon_lat(self):          # the QGIS algorithm's crest reader hands over model-CRS metres
        short = [(400000.0, 5200000.0), (400010.0, 5200000.0)]
        long_ = [(400500.0, 5200500.0), (400700.0, 5200500.0)]
        self.assertEqual(DF.pick_dam_line([short, long_])[0], long_)
        j, note = DF.pick_dam_line([[(400000.0, 5200000.0), (400100.0, 5200000.0)], [(400100.0, 5200000.0), (400200.0, 5200000.0)]])
        self.assertEqual(len(j), 3)

    def test_a_junction_of_three_parts_is_not_joined(self):
        a, b, c = [(0, 47), (1e-3, 47)], [(1e-3, 47), (2e-3, 47)], [(1e-3, 47), (1e-3, 47.001)]
        self.assertEqual(len(DF.merge_lines([a, b, c])), 3)

    def test_one_part_multi_has_a_note_only_when_asked(self):
        self.assertEqual(DF.pick_dam_line([[(0, 47), (1e-3, 47)]])[1], "")
        self.assertIn("one part", DF.pick_dam_line([[(0, 47), (1e-3, 47)]], "dam_line.geojson", multi=True)[1])

    def test_nothing_usable_gives_none(self):
        self.assertEqual(DF.pick_dam_line([]), (None, ""))
        self.assertEqual(DF.pick_dam_line([[(0, 47)]]), (None, ""))


class TestRead(Folder):
    def test_a_multilinestring_with_one_part_is_the_dam_line(self):
        self.put(multi([(-97.0, 47.0), (-97.001, 47.0005), (-97.002, 47.001)]))
        info = DF.read(self.tmp)
        self.assertEqual(info["dam_line"], [(-97.0, 47.0), (-97.001, 47.0005), (-97.002, 47.001)])
        self.assertIn("MultiLineString with one part", info["dam_line_note"])

    def test_parts_that_meet_become_one_line_with_a_note(self):
        self.put(multi([(-97.0, 47.0), (-97.001, 47.0)], [(-97.001, 47.0), (-97.002, 47.0)]))
        info = DF.read(self.tmp)
        self.assertEqual(len(info["dam_line"]), 3)
        self.assertIn("joined end to end", info["dam_line_note"])
        self.assertIn("dam_line.geojson", info["dam_line_note"])

    def test_disjoint_parts_use_the_longest(self):
        self.put(multi([(-97.0, 47.0), (-97.0001, 47.0)], [(-97.01, 47.0), (-97.012, 47.0)]))
        info = DF.read(self.tmp)
        self.assertEqual(info["dam_line"][0], (-97.01, 47.0))
        self.assertIn("longest", info["dam_line_note"])

    def test_a_linestring_still_reads_as_before(self):
        self.put(feature({"type": "LineString", "coordinates": [[-97.0, 47.0], [-97.001, 47.0]]}))
        info = DF.read(self.tmp)
        self.assertEqual(info["dam_line"], [(-97.0, 47.0), (-97.001, 47.0)])
        self.assertEqual(info["dam_line_note"], "")

    def test_a_z_coordinate_is_dropped(self):
        self.put(multi([(-97.0, 47.0, 500.0), (-97.001, 47.0, 501.0)]))
        self.assertEqual(DF.read(self.tmp)["dam_line"], [(-97.0, 47.0), (-97.001, 47.0)])

    def test_an_empty_multilinestring_is_no_line(self):
        self.put(multi())
        info = DF.read(self.tmp)
        self.assertIsNone(info["dam_line"])
        self.assertEqual(info["dam_line_note"], "")

    def test_a_pack_with_both_a_point_and_a_multilinestring_reads_both(self):
        self.put(multi([(-97.0, 47.0), (-97.001, 47.0)]))
        self.put(feature({"type": "Point", "coordinates": [-97.0005, 47.0001]}), "breach_point.geojson")
        info = DF.read(self.tmp)
        self.assertEqual(info["breach_point"], (-97.0005, 47.0001))
        self.assertEqual(len(info["dam_line"]), 2)


class TestRasters(Folder):
    def test_read_geojson_coords_joins_and_picks_the_longest(self):
        p = self.put(multi([(0, 47), (1e-3, 47)], [(1e-3, 47), (2e-3, 47)]))
        self.assertEqual(R.read_geojson_coords(p, "line"), [(0.0, 47.0), (1e-3, 47.0), (2e-3, 47.0)])
        p = self.put(multi([(0, 47), (1e-4, 47)], [(0.5, 47), (0.51, 47)]))
        self.assertEqual(R.read_geojson_coords(p, "line"), [(0.5, 47.0), (0.51, 47.0)])


class TestScreener(Folder):
    def test_the_screener_reads_the_dam_folder_through_the_same_function(self):
        from damit_screener.core import runner_bridge as RB
        df = RB.modules()[1]
        self.assertIs(df, DF)
        self.put(multi([(-97.0, 47.0), (-97.001, 47.0)], [(-97.001, 47.0), (-97.002, 47.0)]))
        info = df.read(self.tmp)
        self.assertEqual(len(info["dam_line"]), 3)
        self.assertIn("joined end to end", info["dam_line_note"])


class TestModelParams(Folder):
    def setUp(self):
        super().setUp()
        self.dem = os.path.join(self.tmp, "dem.tif")
        open(self.dem, "w").close()
        self.values = {"HEIGHT_FT": 40, "STORAGE_ACFT": 500, "TOP_FT": 1900, "DEM": self.dem}

    def test_the_note_reaches_the_run_notes_and_the_line_the_model(self):
        from damit_runner.core import rundam as RD
        self.put(multi([(-97.0, 47.0), (-97.001, 47.0)], [(-97.001, 47.0), (-97.002, 47.0)]))
        info = DF.read(self.tmp)
        p, notes = RD.model_params(self.values, {"dam": {}}, info)
        self.assertEqual(len(p["dam_line_lonlat"]), 3)
        self.assertTrue([n for n in notes if "MultiLineString of 2 parts" in n], notes)

    def test_a_linestring_adds_no_note(self):
        from damit_runner.core import rundam as RD
        self.put(feature({"type": "LineString", "coordinates": [[-97.0, 47.0], [-97.001, 47.0]]}))
        p, notes = RD.model_params(self.values, {"dam": {}}, DF.read(self.tmp))
        self.assertEqual(len(p["dam_line_lonlat"]), 2)
        self.assertFalse([n for n in notes if "MultiLineString" in n])


if __name__ == "__main__":
    unittest.main()
