import unittest
from src.score import score
from src.cost import percentile, local_scenario
from src.run import load_data, prompt_for, decode_response
from src.report import summarise


class EvaluationTests(unittest.TestCase):
    def test_case_insensitive_exact_match_and_no_repair(self):
        words = ["blood pressure", "body mass index"]
        self.assertEqual(
            score(" blood pressure\n", "blood pressure", words)[:2], (1, "correct")
        )
        self.assertEqual(
            score("Blood Pressure", "blood pressure", words)[:2], (1, "correct")
        )
        self.assertEqual(
            score("BLOOD PRESSURE", "blood pressure", words)[:2], (1, "correct")
        )
        for text in [
            "",
            "blood pressure.",
            '"blood pressure"',
            "Answer: blood pressure",
            "blood\npressure",
        ]:
            self.assertEqual(
                score(text, "blood pressure", words)[:2], (0, "parse_error")
            )

    def test_fifty_disjoint_and_hidden_answers(self):
        test, words = load_data("test")
        dev, _ = load_data("dev")
        self.assertEqual(len(test), 50)
        self.assertFalse(
            {r["abbreviation"] for r in test} & {r["abbreviation"] for r in dev}
        )
        self.assertNotIn(test[0]["expected"], prompt_for(test[0], words))
        self.assertNotIn("HIDDEN_SENTINEL", prompt_for(test[0], ["HIDDEN_SENTINEL"]))

    def test_percentiles(self):
        self.assertAlmostEqual(percentile(list(range(1, 51)), 0.5), 25.5)
        self.assertAlmostEqual(percentile(list(range(1, 51)), 0.95), 47.55)

    def test_local_cost(self):
        s = {
            "hardware_usd_per_hour": 1,
            "labour_hours_per_month": 2,
            "labour_usd_per_hour": 10,
            "requests_per_month": 1000,
            "available_hours_per_month": 160,
        }
        c = local_scenario(3.6, s)
        self.assertEqual(c["today_usd"], 21)
        self.assertEqual(c["100x_usd"], 120)

    def test_local_decode_truncation(self):
        m = {"provider": "ollama", "model": "qwen2.5:1.5b"}
        self.assertEqual(
            decode_response({"done_reason": "length", "message": {"content": "x"}}, m)[
                1
            ],
            "truncated",
        )

    def test_three_model_summary_keeps_failures(self):
        cfg = {
            "local_cost": {
                "hardware_usd_per_hour": 0.15,
                "labour_hours_per_month": 1,
                "labour_usd_per_hour": 5,
                "requests_per_month": 1000,
                "available_hours_per_month": 160,
            },
            "models": [{"role": "small_local", "model": "a", "provider": "ollama"}],
        }
        rows = [
            {
                "role": "small_local",
                "latency_ms": "100",
                "correct": "1",
                "status": "correct",
                "eval_count": "5",
                "eval_duration_ns": "1000000000",
            },
            {
                "role": "small_local",
                "latency_ms": "1000",
                "correct": "0",
                "status": "timeout",
                "eval_count": "0",
                "eval_duration_ns": "0",
            },
        ]
        s = summarise(rows, cfg)[0]
        self.assertEqual(s["accuracy"], 0.5)
        self.assertEqual(s["timeouts"], 1)
        self.assertEqual(s["p50_ms"], 550)
        self.assertNotEqual(s["cost_per_1k_usd"], "")


class RefactorTests(unittest.TestCase):
    def test_explicit_refusals_are_wrong_and_separately_counted(self):
        words = ["blood pressure"]
        for output in (
            "I cannot help with that.",
            "Sorry, I can't answer.\nAsk someone else.",
        ):
            self.assertEqual(score(output, "blood pressure", words)[:2], (0, "refusal"))

    def test_saved_raw_evidence_reproduces_original_scores(self):
        from src import run, report

        path = run.ROOT / "results/runs/test-local3-20260913T183731049814Z"
        rows, metadata = report.validate_run(path)
        summary = report.summarise(rows, metadata["settings"])
        self.assertEqual([row["correct"] for row in summary], [16, 16, 27])
        self.assertEqual([row["n"] for row in summary], [50, 50, 50])

    def test_invalid_config_is_rejected(self):
        import copy
        from src import run

        original = run.read_json(run.ROOT / "config.json")
        for key, value in [
            ("requests_per_month", 0),
            ("available_hours_per_month", -1),
            ("hardware_usd_per_hour", float("nan")),
        ]:
            config = copy.deepcopy(original)
            config["local_cost"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                run.validate_config(config)
        config = copy.deepcopy(original)
        config["models"][1]["model"] = config["models"][0]["model"]
        with self.assertRaises(ValueError):
            run.validate_config(config)

    def test_corrupted_or_incomplete_evidence_cannot_be_published(self):
        import csv
        import json
        import shutil
        import tempfile
        from pathlib import Path
        from src import run, report

        source = run.ROOT / "results/runs/test-local3-20260913T183731049814Z"
        published = (run.ROOT / "results/per_item.csv").read_bytes()
        for problem in ("missing", "duplicate", "score", "tokens", "incomplete"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "run"
                shutil.copytree(source, path)
                with (path / "per_item.csv").open(
                    newline="", encoding="utf-8"
                ) as stream:
                    rows = list(csv.DictReader(stream))
                if problem == "missing":
                    rows.pop()
                elif problem == "duplicate":
                    rows.append(rows[0])
                elif problem == "score":
                    rows[0]["correct"] = "1"
                elif problem == "tokens":
                    rows[0]["output_tokens"] = "999"
                else:
                    metadata = run.read_json(path / "metadata.json")
                    metadata["complete"] = False
                    (path / "metadata.json").write_text(
                        json.dumps(metadata), encoding="utf-8"
                    )
                report.write_csv(path / "per_item.csv", run.FIELDS, rows)
                with self.assertRaises(ValueError):
                    report.generate(path, publish=True)
                self.assertEqual(
                    (run.ROOT / "results/per_item.csv").read_bytes(), published
                )

    def test_shared_loop_preserves_failures_and_practice_isolation(self):
        import contextlib
        import io
        import shutil
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from src import run, report

        for practice, expected_calls in ((True, 10), (False, 150)):
            with self.subTest(practice=practice), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for directory in ("src", "data"):
                    shutil.copytree(run.ROOT / directory, root / directory)
                shutil.copyfile(run.ROOT / "config.json", root / "config.json")
                responses = iter(
                    [
                        TimeoutError(),
                        {"message": None},
                        {
                            "message": {"content": "blood pressure"},
                            "done_reason": "length",
                        },
                    ]
                )

                def model_response(*args):
                    response = next(
                        responses, {"message": {"content": "blood pressure"}}
                    )
                    if isinstance(response, Exception):
                        raise response
                    return response

                with (
                    patch.object(run, "ROOT", root),
                    patch.object(report, "ROOT", root),
                    patch.object(run, "preflight", return_value={}),
                    patch.object(
                        run, "call_model", side_effect=model_response
                    ) as calls,
                    patch.object(run.time, "sleep"),
                    patch.object(report, "generate") as publish,
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    directory = run.benchmark(practice=practice)
                    rows, metadata = report.validate_run(directory)
                    self.assertEqual(calls.call_count, expected_calls)
                    self.assertEqual(len(rows), expected_calls)
                    self.assertEqual(
                        [row["status"] for row in rows[:3]],
                        ["timeout", "response_error", "truncated"],
                    )
                    self.assertTrue(all(row["correct"] == "0" for row in rows[:3]))
                    self.assertEqual(metadata["split"], "dev" if practice else "test")
                    publish.assert_called_once_with(directory, publish=not practice)
                    if not practice:
                        order = [call.args[0]["role"] for call in calls.call_args_list]
                        self.assertEqual(
                            order,
                            ["small_local"] * 50
                            + ["medium_local"] * 50
                            + ["large_local"] * 50,
                        )


if __name__ == "__main__":
    unittest.main()
