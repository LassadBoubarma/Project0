import csv, json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import dashboard as dash, run


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=dash.ROOT.parent)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        for folder in ("src", "data", "results"):
            shutil.copytree(
                dash.ROOT / folder,
                self.root / folder,
                ignore=shutil.ignore_patterns("__pycache__", "runs"),
            )
        shutil.copyfile(dash.ROOT / "config.json", self.root / "config.json")
        self.patches = [
            patch.object(dash, "ROOT", self.root),
            patch.object(run, "ROOT", self.root),
        ]
        for p in self.patches:
            p.start()
        self.cfg = run.read_json(self.root / "config.json")
        self.items, _ = run.load_data("test")

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def fixture(self, complete=True, split="test", missing=False):
        path = self.root / "results/runs/test-fixture"
        path.mkdir(parents=True)
        meta = {
            "settings": self.cfg,
            "split": split,
            "complete": complete,
            "scope": "three_local_models",
            "item_ids": [i["id"] for i in self.items],
        }
        (path / "metadata.json").write_text(json.dumps(meta))
        (path / "items.json").write_text(json.dumps(self.items))
        with (path / "per_item.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=run.FIELDS)
            w.writeheader()
            for mi, m in enumerate(self.cfg["models"]):
                for index, item in enumerate(self.items):
                    if missing and mi == 2 and index == 49:
                        continue
                    r = {k: "" for k in run.FIELDS}
                    r.update(
                        role=m["role"],
                        model=m["model"],
                        item_id=item["id"],
                        expected=item["expected"],
                        abbreviation=item["abbreviation"],
                        output=item["expected"],
                        correct="1",
                        status="correct",
                        latency_ms=str(100 + mi * 50),
                        eval_count="5",
                        eval_duration_ns="1000000000",
                    )
                    w.writerow(r)
        return path

    def test_empty_is_not_zero_accuracy(self):
        data = dash.dashboard_data()
        self.assertFalse(data["comparable"])
        self.assertEqual(len(data["models"]), 3)
        self.assertTrue(all(m["accuracy"] is None for m in data["models"]))

    def test_complete_three_local_comparison(self):
        self.fixture()
        data = dash.dashboard_data()
        self.assertTrue(data["comparable"])
        self.assertEqual(
            set(data["winners"]), {"small_local", "medium_local", "large_local"}
        )
        self.assertTrue(all(m["count"] == 50 for m in data["models"]))
        self.assertTrue(all(m["cost"] is not None for m in data["models"]))

    def test_incomplete_never_wins(self):
        self.fixture(complete=False)
        self.assertFalse(dash.dashboard_data()["comparable"])

    def test_missing_row_rejected_as_comparable(self):
        self.fixture(missing=True)
        self.assertFalse(dash.dashboard_data()["comparable"])

    def test_path_traversal_rejected(self):
        self.fixture()
        with self.assertRaises(ValueError):
            dash.selected_path("../../config.json")

    def test_model_readiness_uses_all_three(self):
        with patch.object(
            run,
            "request_json",
            return_value={"models": [{"name": m["model"]} for m in self.cfg["models"]]},
        ):
            self.assertTrue(dash.models_ready(self.cfg))


if __name__ == "__main__":
    unittest.main()
