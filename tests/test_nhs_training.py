import json
import unittest
from pathlib import Path
from src.generate_training_data import generate_sft_dataset

ROOT = Path(__file__).resolve().parents[1]


class NHSTrainingDataTests(unittest.TestCase):
    def test_glossary_structure(self):
        glossary_path = ROOT / "data/training_glossary.json"
        self.assertTrue(glossary_path.exists())
        items = json.loads(glossary_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(items), 50)
        for item in items:
            self.assertIn("abbreviation", item)
            self.assertIn("expansion", item)
            self.assertIn("example_contexts", item)
            self.assertGreaterEqual(len(item["example_contexts"]), 1)

    def test_generate_sft_dataset(self):
        records = generate_sft_dataset()
        self.assertGreater(len(records), 100)
        for r in records:
            self.assertIn("messages", r)
            self.assertEqual(len(r["messages"]), 2)
            self.assertEqual(r["messages"][0]["role"], "user")
            self.assertEqual(r["messages"][1]["role"], "assistant")
            self.assertTrue(r["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
