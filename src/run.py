"""Sequential three-local-model benchmark runner. Raw responses are retained and never repaired/retried."""

import argparse
import csv
import hashlib
import json
import os
import platform
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from src.score import score

ROOT = Path(__file__).resolve().parents[1]

FIELDS = [
    "role",
    "model",
    "resolved_model",
    "item_id",
    "abbreviation",
    "expected",
    "output",
    "parsed",
    "correct",
    "status",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "eval_count",
    "eval_duration_ns",
    "timestamp_utc",
    "error",
]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_data(split):
    path = ROOT / "data" / ("items.jsonl" if split == "test" else "dev.jsonl")
    items = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    vocab = read_json(ROOT / "data/word_list.json")
    if len({r["id"] for r in items}) != len(items):
        raise ValueError("Duplicate item ID")
    if len({r["abbreviation"] for r in items}) != len(items):
        raise ValueError("Duplicate abbreviation")
    if not items or not all(r["expected"] in vocab for r in items):
        raise ValueError("Empty dataset or label outside fixed vocabulary")
    if split == "test":
        if len(items) < 50:
            raise ValueError("Final benchmark requires at least 50 test items")
    return items, vocab


def prompt_for(item, vocab=None):
    # Gold answers and the word list are intentionally NOT inserted into the model prompt.
    return (
        (ROOT / "src/prompt.txt")
        .read_text(encoding="utf-8")
        .format(context=item["context"], abbreviation=item["abbreviation"])
    )


def request_json(url, payload=None, headers=None, timeout=180):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def call_model(model, prompt, cfg):
    if model["provider"] != "ollama":
        raise ValueError("This version supports local Ollama models only.")
    return request_json(
        "http://localhost:11434/api/chat",
        {
            "model": model["model"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "temperature": cfg["temperature"],
                "num_predict": cfg["max_output_tokens"],
                "num_ctx": 8192,
            },
        },
        timeout=cfg["timeout_seconds"],
    )


def decode_response(raw, model):
    return (
        raw.get("message", {}).get("content", ""),
        ("truncated" if raw.get("done_reason") == "length" else ""),
        {
            "resolved_model": raw.get("model", model["model"]),
            "input_tokens": raw.get("prompt_eval_count", ""),
            "output_tokens": raw.get("eval_count", ""),
            "eval_count": raw.get("eval_count", ""),
            "eval_duration_ns": raw.get("eval_duration", ""),
        },
    )


def fingerprint():
    files = [
        "config.json",
        "data/items.jsonl",
        "data/dev.jsonl",
        "data/word_list.json",
        "data/label_reviews.csv",
        "src/prompt.txt",
        "src/run.py",
        "src/score.py",
        "src/cost.py",
    ]
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files
    }


def reviews_ready(items):
    with (ROOT / "data/label_reviews.csv").open(encoding="utf-8", newline="") as f:
        reviews = {row["id"]: row for row in csv.DictReader(f)}
    return all(
        (r := reviews.get(item["id"], {})).get("reviewer_1", "").strip()
        and r.get("reviewer_2", "").strip()
        and r["reviewer_1"].strip().casefold() != r["reviewer_2"].strip().casefold()
        and r.get("checked_date", "").strip()
        and r.get("expected") == item["expected"]
        for item in items
    )


def local_cost_ready(cfg):
    settings = cfg.get("local_cost", {})
    required = (
        "hardware_usd_per_hour",
        "labour_hours_per_month",
        "labour_usd_per_hour",
        "requests_per_month",
        "available_hours_per_month",
    )
    if any(settings.get(k) is None for k in required):
        return False
    try:
        import math

        return (
            all(
                math.isfinite(float(settings[k])) and float(settings[k]) >= 0
                for k in required
            )
            and settings["requests_per_month"] > 0
            and settings["available_hours_per_month"] > 0
        )
    except (TypeError, ValueError):
        return False


def _command_output(command):
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=8, check=False
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def hardware_snapshot(model_records, ollama_version):
    info = {
        "models": model_records,
        "ollama_version": ollama_version,
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "ram_gb": "",
        "gpu": "",
    }
    if os.name == "nt":
        cpu = _command_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)",
            ]
        )
        ram = _command_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1)",
            ]
        )
        gpu = _command_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                '(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) -join "; "',
            ]
        )
        info["cpu"] = cpu or info["cpu"]
        info["ram_gb"] = ram
        info["gpu"] = gpu
    else:
        info["gpu"] = _command_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]
        )
    return info


def preflight(cfg):
    tags = request_json("http://localhost:11434/api/tags", timeout=10)
    available = {m.get("name"): m for m in tags.get("models", [])}
    missing = [m["model"] for m in cfg["models"] if m["model"] not in available]
    if missing:
        raise ValueError(
            "Missing Ollama model(s): "
            + ", ".join(missing)
            + ". Run ollama pull for each one."
        )
    version = request_json("http://localhost:11434/api/version", timeout=10)
    records = {m["role"]: available[m["model"]] for m in cfg["models"]}
    return hardware_snapshot(records, version)


def validate_config(cfg):
    """Reject settings that would make the comparison invalid."""
    models = cfg.get("models", [])
    if len(models) != 3 or len({m["model"] for m in models}) != 3:
        raise ValueError("Configure three distinct local models.")
    if len({m["role"] for m in models}) != 3 or any(
        m["provider"] != "ollama" for m in models
    ):
        raise ValueError("Each model needs a unique role and provider=ollama.")
    if cfg.get("temperature") != 0:
        raise ValueError("Temperature must be 0.")
    for key in ("max_output_tokens", "timeout_seconds"):
        if cfg.get(key, 0) <= 0:
            raise ValueError(key + " must be positive.")
    if cfg.get("pause_seconds", -1) < 0 or not local_cost_ready(cfg):
        raise ValueError("Check pause_seconds and local_cost in config.json.")


def check_project():
    """Offline checks; no inference, downloads or changes to saved results."""
    cfg = read_json(ROOT / "config.json")
    validate_config(cfg)
    test, vocab = load_data("test")
    dev, _ = load_data("dev")
    for key in ("id", "abbreviation"):
        if {i[key] for i in test} & {i[key] for i in dev}:
            raise ValueError("Development and test sets overlap: " + key)
    if not reviews_ready(test):
        raise ValueError("Complete the two-person review records.")
    for item in test + dev:
        if score(item["expected"], item["expected"], vocab)[0] != 1:
            raise ValueError("Invalid gold label: " + item["id"])
        if item["expected"].casefold() in prompt_for(item).casefold():
            raise ValueError("Gold answer leaked into prompt: " + item["id"])
    print(
        f"PASS: {len(test)} test / {len(dev)} dev items; three local models; shared prompt and scorer."
    )
    print(
        "PASS: two distinct reviewer names recorded per test item (not independent verification)."
    )
    latest = ROOT / "results/latest_run.txt"
    if latest.exists():
        from src.report import validate_run, summarise

        directory = ROOT / latest.read_text(encoding="utf-8").strip().replace("\\", "/")
        rows, meta = validate_run(directory)
        summary = summarise(rows, meta["settings"])
        print(
            "PASS: saved evidence is complete:",
            ", ".join(f"{s['model']} {s['correct']}/{s['n']}" for s in summary),
        )
        from pypdf import PdfReader

        if len(PdfReader(ROOT / "report.pdf").pages) != 2:
            raise ValueError("report.pdf must have two pages.")
        print("PASS: report.pdf has two pages.")
    print(
        "Local-only adaptation: original API/API/local requirement and empirical API break-even remain unmet."
    )


def setup():
    """Create an isolated Python environment and fetch the configured local models."""
    import shutil
    import sys
    import venv

    if sys.version_info < (3, 10):
        raise ValueError("Install Python 3.10 or newer.")
    if not shutil.which("ollama"):
        raise ValueError(
            "Install and start Ollama from https://ollama.com, then rerun setup."
        )
    venv.create(ROOT / ".venv", with_pip=True)
    python = (
        ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")],
        check=True,
    )
    installed = {
        model["name"]
        for model in request_json("http://localhost:11434/api/tags", timeout=10)[
            "models"
        ]
    }
    for model in read_json(ROOT / "config.json")["models"]:
        if model["model"] not in installed:
            subprocess.run(["ollama", "pull", model["model"]], check=True)
    print("Setup complete. Start with: .venv/Scripts/python.exe -m src.dashboard")


def benchmark(split="test", practice=False):
    """One loop for both practice and the final benchmark."""
    if practice:
        split = "dev"
    cfg = read_json(ROOT / "config.json")
    validate_config(cfg)
    items, vocab = load_data(split)
    if split == "test" and not reviews_ready(items):
        raise ValueError("Complete data/label_reviews.csv before the final run.")
    if practice:
        cfg = {**cfg, "models": cfg["models"][:1]}
    # Import before making requests so missing report dependencies fail early.
    from src.report import generate

    hardware = preflight(cfg)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = ROOT / "results" / "runs" / (split + "-local3-" + stamp)
    destination.mkdir(parents=True)
    metadata = {
        "started_utc": stamp,
        "split": split,
        "scope": "small_model_practice" if practice else "three_local_models",
        "settings": cfg,
        "sha256": fingerprint(),
        "hardware": hardware,
        "item_ids": [r["id"] for r in items],
        "complete": False,
        "latency_policy": "Full request wall time for every attempt; any model loading during requests included; pauses excluded.",
        "retries": 0,
    }
    (destination / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    (destination / "items.json").write_text(
        json.dumps(items, indent=2), encoding="utf-8"
    )
    (destination / "prompts.json").write_text(
        json.dumps([prompt_for(r, vocab) for r in items], indent=2), encoding="utf-8"
    )

    with (
        (destination / "per_item.csv").open("w", newline="", encoding="utf-8") as f,
        (destination / "raw.jsonl").open("w", encoding="utf-8") as rawfile,
    ):
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for model in cfg["models"]:
            print("\n===", model["model"], "===", flush=True)
            for item in items:
                row = {key: "" for key in FIELDS}
                row.update(
                    role=model["role"],
                    model=model["model"],
                    item_id=item["id"],
                    abbreviation=item["abbreviation"],
                    expected=item["expected"],
                    correct=0,
                    timestamp_utc=datetime.now(timezone.utc).isoformat(),
                )
                start = time.perf_counter()
                raw = None
                try:
                    raw = call_model(model, prompt_for(item, vocab), cfg)
                    row["latency_ms"] = (time.perf_counter() - start) * 1000
                    output, forced, usage = decode_response(raw, model)
                    correct, status, parsed = score(output, item["expected"], vocab)
                    row.update(
                        output=output,
                        parsed=parsed,
                        correct=0 if forced else correct,
                        status=forced or status,
                        **usage,
                    )
                except (TimeoutError, socket.timeout):
                    row.update(status="timeout", error="Request deadline exceeded")
                except urllib.error.URLError as exc:
                    is_timeout = isinstance(exc.reason, (TimeoutError, socket.timeout))
                    row.update(
                        status="timeout" if is_timeout else "connection_error",
                        error=type(exc.reason).__name__,
                    )
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    row.update(status="response_error", error=type(exc).__name__)
                if row["latency_ms"] == "":
                    row["latency_ms"] = (time.perf_counter() - start) * 1000
                writer.writerow(row)
                f.flush()
                rawfile.write(
                    json.dumps(
                        {
                            "role": model["role"],
                            "item_id": item["id"],
                            "response": raw,
                            "error": row["error"],
                        }
                    )
                    + "\n"
                )
                rawfile.flush()
                print(
                    model["role"],
                    item["id"],
                    row["status"],
                    f"{row['latency_ms']:.0f} ms",
                    flush=True,
                )
                time.sleep(cfg["pause_seconds"])

    metadata["complete"] = True
    metadata["finished_utc"] = datetime.now(timezone.utc).isoformat()
    (destination / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    generate(destination, publish=split == "test")
    print("Saved:", destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--setup",
        action="store_true",
        help="Install dependencies and pull the three models",
    )
    actions.add_argument(
        "--check",
        action="store_true",
        help="Check data and saved evidence without model calls",
    )
    actions.add_argument(
        "--practice", action="store_true", help="Run 10 dev items on the small model"
    )
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    args = parser.parse_args()
    if args.setup:
        setup()
    elif args.check:
        check_project()
    else:
        benchmark("dev" if args.practice else args.split, practice=args.practice)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc))
