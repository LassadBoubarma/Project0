"""Local results dashboard. Start: python -m src.dashboard (no extra packages).

Serves only the dashboard and selected experiment data, never the project tree.
Reuses the existing prompt, request adapter, scorer and metric calculations.
"""

import argparse
import csv
import json
import secrets
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from src import run
from src.report import summarise

ROOT = Path(__file__).resolve().parents[1]
TOKEN = secrets.token_urlsafe(32)
JOB_LOCK = threading.Lock()
JOB = {"running": False, "mode": None, "exit_code": None, "log": []}


def models_ready(cfg):
    try:
        tags = run.request_json("http://localhost:11434/api/tags", timeout=5)
        names = {m.get("name") for m in tags.get("models", [])}
        return all(m["model"] in names for m in cfg["models"])
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def read_rows(path):
    if not path.exists():
        return []
    # The benchmark flushes each row. Ignore a row still being written.
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [
        r
        for r in rows
        if r.get("status")
        and r.get("correct") in ("0", "1")
        and r.get("latency_ms")
        and r.get("item_id")
        and r.get("error") is not None
    ]


def runs():
    folder = ROOT / "results/runs"
    found = []
    if folder.exists():
        for path in sorted(folder.iterdir(), reverse=True):
            if path.is_dir() and (path / "metadata.json").exists():
                try:
                    meta = run.read_json(path / "metadata.json")
                    found.append(
                        {
                            "id": path.name,
                            "split": meta.get("split", "unknown"),
                            "complete": bool(meta.get("complete")),
                            "scope": meta.get("scope", "three_local_models"),
                            "started": meta.get("started_utc", path.name),
                        }
                    )
                except (ValueError, OSError):
                    continue  # Retry on the next poll while metadata is being written.
    return found


def selected_path(identifier):
    if identifier not in {r["id"] for r in runs()}:
        raise ValueError("Select an existing experiment.")
    return ROOT / "results/runs" / identifier


def metrics(rows, cfg, target_count):
    """Use the report's calculations so the UI and CSV cannot drift apart."""
    summaries = {s["role"]: s for s in summarise(rows, cfg)}
    result = []
    for model in cfg["models"]:
        summary = summaries.get(model["role"], {})
        count = summary.get("n", 0)
        correct = summary.get("correct", 0)
        result.append(
            {
                "role": model["role"],
                "model": model["model"],
                "count": count,
                "target": target_count,
                "correct": correct,
                "incorrect": count - correct,
                "accuracy": summary.get("accuracy"),
                "p50": summary.get("p50_ms"),
                "p95": summary.get("p95_ms"),
                "cost": summary.get("cost_per_1k_usd"),
                "cost_note": summary.get("cost_status", "No measurements yet"),
                "tokens_per_second": summary.get("local_generation_tokens_per_second")
                or None,
            }
        )
    return result


def dashboard_data(identifier=""):
    catalogue = runs()
    cfg = run.read_json(ROOT / "config.json")
    meta = {}
    rows = []
    items = []
    selected = ""
    if identifier or catalogue:
        selected = identifier or catalogue[0]["id"]
        path = selected_path(selected)
        meta = run.read_json(path / "metadata.json")
        cfg = meta["settings"]  # Never recalculate old runs using new model prices.
        rows = read_rows(path / "per_item.csv")
        if (path / "items.json").exists():
            items = run.read_json(path / "items.json")
    count = len(meta.get("item_ids", [])) or len(run.load_data("test")[0])
    summaries = metrics(rows, cfg, count)
    # Rank only complete, comparable three-model test runs on identical item IDs.
    comparable = (
        bool(meta.get("complete")) and meta.get("split") == "test" and count >= 50
    )
    comparable = (
        comparable
        and len(cfg["models"]) == 3
        and len({m["model"] for m in cfg["models"]}) == 3
    )
    for model in cfg["models"]:
        comparable = comparable and [
            r["item_id"] for r in rows if r["role"] == model["role"]
        ] == meta.get("item_ids")
    winners = []
    if comparable:
        best = max(s["correct"] for s in summaries)
        winners = [s["role"] for s in summaries if s["correct"] == best]
    test_items, _ = run.load_data("test")
    try:
        reviewed = bool(run.reviews_ready(test_items))
    except (OSError, ValueError, KeyError):
        reviewed = False
    with JOB_LOCK:
        job = {**JOB, "log": JOB["log"][-30:]}
    return {
        "runs": catalogue,
        "selected": selected,
        "split": meta.get("split"),
        "complete": bool(meta.get("complete")),
        "scope": meta.get("scope", "three_local_models"),
        "comparable": bool(comparable),
        "winners": winners,
        "models": summaries,
        "rows": rows,
        "items": items,
        "expected_total": count * len(cfg["models"]),
        "job": job,
        "models_ready": models_ready(cfg),
        "reviews_ready": reviewed,
        "cost_ready": run.local_cost_ready(cfg),
        "csrf": TOKEN,
    }


def start_job(mode):
    if mode not in ("local", "test"):
        raise ValueError("Unknown run type.")
    run.validate_config(run.read_json(ROOT / "config.json"))
    if mode == "test":
        if not models_ready(run.read_json(ROOT / "config.json")):
            raise ValueError("Download all three Ollama models first; see README.md.")
        if not run.reviews_ready(run.load_data("test")[0]):
            raise ValueError(
                "Complete both human label reviews before running the final test."
            )
        if not run.local_cost_ready(run.read_json(ROOT / "config.json")):
            raise ValueError(
                "Fill the three local_cost assumptions in config.json before the final test; see README.md."
            )
    with JOB_LOCK:
        if JOB["running"]:
            raise ValueError("A run is already in progress. Wait for it to finish.")
        JOB.update(running=True, mode=mode, exit_code=None, log=[])

    def worker():
        command = (
            [sys.executable, "-u", "-m", "src.run", "--practice"]
            if mode == "local"
            else [sys.executable, "-u", "-m", "src.run"]
        )
        try:
            with subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            ) as process:
                for line in process.stdout:
                    # Prevent accidentally exposing a key if an underlying error ever includes it.
                    with JOB_LOCK:
                        JOB["log"] = (JOB["log"] + [line.rstrip()])[-30:]
                code = process.wait()
        except OSError as exc:
            code = 1
            with JOB_LOCK:
                JOB["log"].append(
                    type(exc).__name__ + ": could not start the Python process."
                )
        with JOB_LOCK:
            JOB.update(running=False, exit_code=code)

    threading.Thread(target=worker, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, body, kind="application/json; charset=utf-8", status=200):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in (f"localhost:{port}", f"127.0.0.1:{port}")

    def do_GET(self):
        if not self.valid_host():
            return self.reply({"error": "Local access only."}, status=403)
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                return self.reply(
                    (ROOT / "src/dashboard.html").read_bytes(),
                    "text/html; charset=utf-8",
                )
            if parsed.path == "/api/data":
                return self.reply(dashboard_data(query.get("run", [""])[0]))
            if parsed.path == "/api/csv":
                path = selected_path(query.get("run", [""])[0])
                # Raw download preserves the evidence; only this known file is exposed.
                return self.reply(
                    (path / "per_item.csv").read_bytes(), "text/csv; charset=utf-8"
                )
            return self.reply({"error": "Not found"}, status=404)
        except (ValueError, OSError, KeyError) as exc:
            return self.reply({"error": str(exc)}, status=400)

    def do_POST(self):
        if not self.valid_host() or self.headers.get("X-Dashboard-Token") != TOKEN:
            return self.reply(
                {"error": "Refresh the dashboard before starting a run."}, status=403
            )
        if self.path != "/api/start":
            return self.reply({"error": "Not found"}, status=404)
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size < 1024:
                raise ValueError("Invalid request.")
            body = json.loads(self.rfile.read(size))
            start_job(body["mode"])
            return self.reply({"ok": True})
        except (ValueError, KeyError) as exc:
            return self.reply({"error": str(exc)}, status=400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    print("Dashboard: " + url, flush=True)
    print(
        "Keep this terminal open. Ctrl+C stops the dashboard. Let active runs finish first.",
        flush=True,
    )
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
