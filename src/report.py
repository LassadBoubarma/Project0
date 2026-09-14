"""Build metrics and a two-page report from saved benchmark evidence."""

import argparse
import csv
import json
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.run import ROOT, load_data, read_json, reviews_ready
from src.cost import percentile, local_scenario

SUMMARY_FIELDS = [
    "role",
    "model",
    "n",
    "correct",
    "accuracy",
    "parse_errors",
    "refusals",
    "timeouts",
    "other_errors",
    "p50_ms",
    "p95_ms",
    "mean_ms",
    "cost_per_1k_usd",
    "cost_status",
    "local_generation_tokens_per_second",
]


def summarise(rows, cfg):
    results = []
    for model in cfg["models"]:
        batch = [r for r in rows if r["role"] == model["role"]]
        if not batch:
            continue
        n = len(batch)
        times = [float(r["latency_ms"]) for r in batch]
        durations = sum(float(r.get("eval_duration_ns") or 0) for r in batch) / 1e9
        tokens = sum(int(r.get("eval_count") or 0) for r in batch)
        scenario = local_scenario(sum(times) / n / 1000, cfg["local_cost"])
        item = {
            "role": model["role"],
            "model": model["model"],
            "n": n,
            "correct": sum(int(r["correct"]) for r in batch),
            "parse_errors": sum(r["status"] == "parse_error" for r in batch),
            "refusals": sum(r["status"] == "refusal" for r in batch),
            "timeouts": sum(r["status"] == "timeout" for r in batch),
            "other_errors": sum(
                r["status"]
                not in {"correct", "wrong_answer", "parse_error", "refusal", "timeout"}
                for r in batch
            ),
            "p50_ms": percentile(times, 0.5),
            "p95_ms": percentile(times, 0.95),
            "mean_ms": sum(times) / n,
            "cost_per_1k_usd": scenario.get("cost_per_1k_usd", ""),
            "cost_status": scenario["status"],
            "local_generation_tokens_per_second": tokens / durations
            if durations
            else "",
        }
        item["accuracy"] = item["correct"] / n
        results.append(item)
    return results


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def fmt(x, places=2):
    return "pending" if x in ("", None) else f"{float(x):.{places}f}"


def table_markdown(summary):
    lines = [
        "| Model | Correct | Accuracy | p50 ms | p95 ms | USD / 1k | Tokens/s | Parse | Refusal | Timeout | Other |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summary:
        lines.append(
            f"| {s['model']} | {s['correct']}/{s['n']} | {s['accuracy']:.1%} | "
            f"{s['p50_ms']:.0f} | {s['p95_ms']:.0f} | {fmt(s['cost_per_1k_usd'], 4)} | "
            f"{fmt(s['local_generation_tokens_per_second'], 1)} | {s['parse_errors']} | {s['refusals']} | {s['timeouts']} | {s['other_errors']} |"
        )
    if not summary:
        lines.append(
            "| Real benchmark not yet run | pending | pending | pending | pending | pending | pending | pending | pending | pending |"
        )
    return "\n".join(lines)


def build_decision(summary):
    if not summary:
        return "Decision pending real results."
    eligible = [
        s
        for s in summary
        if s["accuracy"] >= 0.95
        and s["p95_ms"] < 10000
        and s["cost_per_1k_usd"] not in ("", None)
    ]
    if eligible:
        chosen = min(
            eligible,
            key=lambda s: (float(s["cost_per_1k_usd"]), -s["accuracy"], s["p95_ms"]),
        )
        return (
            f"Choice: {chosen['model']}. It reaches {chosen['correct']}/{chosen['n']} ({chosen['accuracy']:.1%}), "
            f"p95 {chosen['p95_ms']:.0f} ms and estimated ${float(chosen['cost_per_1k_usd']):.4f}/1k."
        )
    best = max(summary, key=lambda s: (s["accuracy"], -s["p95_ms"]))
    return (
        "No model meets the project's 95% accuracy + p95<10s target. "
        f"For this benchmark, choose the highest-accuracy model: {best['model']} at {best['correct']}/{best['n']} ({best['accuracy']:.1%})."
    )


def write_hardware_note(path, meta, cfg, summary):
    hw = meta.get("hardware", {})
    cost = cfg["local_cost"]
    lines = [
        "# Local hardware and model notes",
        "",
        f"- OS: {hw.get('os', 'not detected')}",
        f"- CPU: {hw.get('cpu', 'not detected')}",
        f"- GPU: {hw.get('gpu', 'not detected')}",
        f"- RAM: {hw.get('ram_gb', 'not detected')} GB",
        f"- Python: {hw.get('python', 'not detected')}",
        "",
        "Models:",
    ]
    records = hw.get("models", {})
    for m in cfg["models"]:
        r = records.get(m["role"], {})
        details = r.get("details", {}) if isinstance(r, dict) else {}
        s = next((x for x in summary if x["role"] == m["role"]), None)
        lines.append(
            f"- {m['model']}: digest {r.get('digest', 'not detected')}; params {details.get('parameter_size', 'not detected')}; "
            f"quantisation {details.get('quantization_level', 'not detected')}; generation "
            f"{fmt(s.get('local_generation_tokens_per_second') if s else None, 1)} tokens/s"
        )
    lines += [
        "",
        "Cost assumptions:",
        f"- Hardware + electricity: ${cost['hardware_usd_per_hour']}/hour",
        f"- Operator time: {cost['labour_hours_per_month']} h/month at ${cost['labour_usd_per_hour']}/h",
        f"- Baseline traffic: {cost['requests_per_month']} requests/month",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_run(run_dir):
    """Reject missing, duplicated, reordered or inconsistent saved evidence."""
    from src.run import decode_response
    from src.score import score

    meta = read_json(run_dir / "metadata.json")
    if not meta.get("complete"):
        raise ValueError("Cannot report an interrupted run as complete.")
    items = read_json(run_dir / "items.json")
    ids = [item["id"] for item in items]
    if ids != meta["item_ids"] or len(set(ids)) != len(ids):
        raise ValueError("Item snapshot does not match metadata.")
    models = meta["settings"]["models"]
    with (run_dir / "per_item.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    raw = [
        json.loads(line)
        for line in (run_dir / "raw.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    keys = [(model["role"], item["id"]) for model in models for item in items]
    if [(r["role"], r["item_id"]) for r in rows] != keys or [
        (r["role"], r["item_id"]) for r in raw
    ] != keys:
        raise ValueError("Missing, extra, duplicated or reordered responses.")
    vocabulary = read_json(ROOT / "data/word_list.json")
    import hashlib

    recorded = meta.get("sha256", {}).get("data/word_list.json")
    if (
        recorded
        and hashlib.sha256((ROOT / "data/word_list.json").read_bytes()).hexdigest()
        != recorded
    ):
        raise ValueError(
            "The saved run used a different vocabulary. Restore it before regenerating."
        )
    item_map = {item["id"]: item for item in items}
    model_map = {model["role"]: model for model in models}
    for row, evidence in zip(rows, raw):
        item, model = item_map[row["item_id"]], model_map[row["role"]]
        if row["expected"] != item["expected"] or row["model"] != model["model"]:
            raise ValueError("Result label or model differs from its snapshot.")
        if float(row["latency_ms"]) < 0 or row["correct"] not in ("0", "1"):
            raise ValueError("Invalid timing or score.")
        response = evidence["response"]
        if response is not None and row["status"] != "response_error":
            output, forced, usage = decode_response(response, model)
            correct, status, parsed = score(output, item["expected"], vocabulary)
            if (row["output"], row["parsed"], row["correct"], row["status"]) != (
                output,
                parsed,
                str(0 if forced else correct),
                forced or status,
            ):
                raise ValueError("CSV does not agree with the raw response and scorer.")
            for key, value in usage.items():
                if str(row[key]) != str(value):
                    raise ValueError("Token usage differs from raw response: " + key)
        elif row["correct"] != "0" or row["status"] not in (
            "timeout",
            "connection_error",
            "response_error",
            "api_error",
        ):
            raise ValueError("Missing response must count as an execution error.")
    return rows, meta


def generate(run_dir, publish=False):
    rows, meta = validate_run(run_dir)
    cfg = meta["settings"]
    target = ROOT if publish else run_dir
    summary = summarise(rows, cfg)
    if publish and (
        meta["split"] != "test" or len(meta["item_ids"]) < 50 or len(cfg["models"]) != 3
    ):
        raise ValueError("Only a full three-model test can be published.")
    write_csv(run_dir / "summary.csv", SUMMARY_FIELDS, summary)
    if publish:
        shutil.copyfile(run_dir / "per_item.csv", ROOT / "results/per_item.csv")
        shutil.copyfile(run_dir / "summary.csv", ROOT / "results/summary.csv")
        (ROOT / "results/latest_run.txt").write_text(
            run_dir.relative_to(ROOT).as_posix() + "\n", encoding="utf-8"
        )
        write_hardware_note(ROOT / "results/hardware.md", meta, cfg, summary)
    scenarios = []
    for s in summary:
        sc = local_scenario(s["mean_ms"] / 1000, cfg["local_cost"])
        sc["model"] = s["model"]
        sc["role"] = s["role"]
        scenarios.append(sc)
    failures = []
    for model in cfg["models"]:
        bad = [
            row
            for row in rows
            if row["role"] == model["role"] and int(row["correct"]) == 0
        ]
        failures.append((model, bad[:3], len(bad)))
    decision = build_decision(summary)

    status = (
        "DRAFT - real benchmark not run"
        if not rows
        else (
            "DEV ONLY - excluded from final results"
            if meta["split"] == "dev"
            else "MEASURED FINAL TEST"
        )
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="BodySmall",
            fontName="Helvetica",
            fontSize=8.5,
            leading=10.5,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyTiny", fontName="Helvetica", fontSize=7.5, leading=9, spaceAfter=4
        )
    )
    styles.add(
        ParagraphStyle(name="CellSmall", fontName="Helvetica", fontSize=6.7, leading=8)
    )
    story = []

    def para(text, style="BodySmall"):
        story.append(Paragraph(escape(text), styles[style]))

    def heading(text):
        para(text, "Heading2")

    def grid(data, widths):
        cells = [
            [Paragraph(escape(str(c)), styles["CellSmall"]) for c in row]
            for row in data
        ]
        table = Table(cells, colWidths=widths, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 6))

    # PAGE 1
    para("Medical abbreviation bake-off - three local model sizes", "Title")
    para("CS496 Project 0 | " + status)
    para(
        "Run: "
        + meta["started_utc"]
        + " | Three-local-model adaptation of the API/API/local brief.",
        "BodyTiny",
    )
    heading("1. Task and example")
    para(
        "Task: expand one medical abbreviation from a short UK medical-record context. The gold answer is hidden from the model and scoring is automatic."
    )
    try:
        example_item = read_json(run_dir / "items.json")[0]
        para(
            f"Example: context: {example_item['context']} Question: What does {example_item['abbreviation']} mean here? Expected: {example_item['expected']}."
        )
    except Exception:
        para("Example item unavailable in this draft.")

    heading("2. Data")
    try:
        review_note = (
            "two distinct reviewer names recorded"
            if reviews_ready(load_data("test")[0])
            else "two-person review pending"
        )
    except Exception:
        review_note = "review status unavailable"
    para(
        f"{len(meta['item_ids'])} {meta['split']} items; the project has 50 test and 10 development items with disjoint abbreviations. Labels come from the NHS abbreviation glossary; contexts are synthetic and contain no patient data. Review records: {review_note}; recorded names are not independent proof of review. Development items were used only for setup; final accuracy uses the 50-item frozen test set."
    )

    heading("3. Setup")
    para(
        "Models: "
        + ", ".join(m["model"] for m in cfg["models"])
        + ". All three run locally through Ollama on the same machine."
    )
    para(
        f"Settings: temperature {cfg['temperature']}; output limit {cfg['max_output_tokens']} tokens; same prompt, same question order, same parser; one sequential call per item; no retries, tools, retrieval or chat history. Scoring trims outer whitespace and ignores letter case, but wording otherwise must match the canonical answer exactly. Timeouts, truncation and malformed outputs count as wrong."
    )
    hw = meta.get("hardware", {}) if meta else {}
    para(
        f"Hardware: CPU {hw.get('cpu', 'not detected')}; GPU {hw.get('gpu', 'not detected')}; RAM {hw.get('ram_gb', 'not detected')} GB. Full detected model metadata is saved in results/hardware.md."
    )
    prompt_summary = read_json(run_dir / "prompts.json")[0].strip().replace("\n", " ")
    if len(prompt_summary) > 420:
        prompt_summary = prompt_summary[:417] + "..."
    para("Prompt: " + prompt_summary, "BodyTiny")

    heading("4. Results")
    data = [
        [
            "Model",
            "Correct",
            "p50 / p95 ms",
            "USD / 1k",
            "tokens/s",
            "Parse/Refusal/Timeout/Other",
        ]
    ]
    for s in summary:
        data.append(
            [
                s["model"],
                f"{s['correct']}/{s['n']} ({s['accuracy']:.0%})",
                f"{s['p50_ms']:.0f} / {s['p95_ms']:.0f}",
                fmt(s["cost_per_1k_usd"], 4),
                fmt(s["local_generation_tokens_per_second"], 1),
                f"{s['parse_errors']}/{s['refusals']}/{s['timeouts']}/{s['other_errors']}",
            ]
        )
    if not summary:
        data += [
            [m["model"], "pending", "pending", "pending", "pending", "pending"]
            for m in cfg["models"]
        ]
    grid(data, [112, 75, 85, 65, 60, 105])
    para(
        "Parse includes out-of-vocabulary answers. Fixed refusal prefixes are counted separately; unrecognised refusal wording can remain a parse error. Latency is full wall-clock request time. p50 and p95 include every attempted request. Cost/1k uses each model's measured throughput plus the same hardware/electricity and operator-time assumptions. All 50 attempts per model remain in the accuracy denominator.",
        "BodyTiny",
    )

    # PAGE 2
    story.append(PageBreak())
    para("Evidence, decision and scaling", "Title")
    heading("4. Results - three wrong answers per model")
    for m, bad, total in failures:
        para(
            m["model"] + " - " + (f"{total} failures" if rows else "pending real run"),
            "BodyTiny",
        )
        for r in bad:
            out = (r["output"] or "[empty]").replace(chr(10), " / ")
            if len(out) > 95:
                out = out[:92] + "..."
            para(
                f"{r['item_id']} ({r['abbreviation']}): expected {r['expected']}; output {out} [{r['status']}].",
                "BodyTiny",
            )
        if rows and total < 3:
            para(
                "Fewer than three failures; no additional examples invented.",
                "BodyTiny",
            )

    heading("5. Choice and when we would change it")
    para(decision)
    para(
        "We would change the choice if a smaller model reached the same required accuracy with materially lower p95 latency/cost, if the larger model gained enough accuracy to justify its slower throughput, or if deployment hardware/cost assumptions changed."
    )

    heading("6. Cost at 100x traffic and break-even")
    cost = cfg["local_cost"]
    para(
        f"All candidates are local: no paid API requests. Estimated hardware/electricity: ${cost['hardware_usd_per_hour']}/hour; operator time: {cost['labour_hours_per_month']} hour/month at ${cost['labour_usd_per_hour']}/hour. Baseline: {cost['requests_per_month']:,} requests/month; 100x: {cost['requests_per_month'] * 100:,}. Costs assume hardware is charged only for active processing time."
    )
    for sc in scenarios:
        para(
            f"{sc['model']}: today ${fmt(sc.get('today_usd'), 3)}; at 100x ${fmt(sc.get('100x_usd'), 3)}; capacity {fmt(sc.get('capacity_per_month'), 0)} requests/month; 100x fits one machine: {sc.get('100x_fits_one_machine')}.",
            "BodyTiny",
        )
    para(
        "For an API price A per request, local variable cost v and monthly labour F, break-even N = F/(A-v), only if A > v and capacity allows. No API was measured, so a numeric API-vs-local break-even is unavailable.",
        "BodyTiny",
    )
    para(
        "Break-even note: because this local-only variant compares three self-hosted models rather than an API model against a self-hosted model, there is no API-vs-local break-even volume to compute. If the original brief is enforced literally, a separate top-API + cheap-API + local run is required to satisfy that item."
    )

    heading("Limitations")
    para(
        "This benchmark measures canonical abbreviation expansion, not clinical competence. Synthetic contexts and 50 test cases limit generalisation; one item changes accuracy by two percentage points. The final run is preserved exactly and is not edited after seeing outputs.",
        "BodyTiny",
    )
    para(
        "Sources: NHS, nhs.uk/nhs-app/help/understanding-abbreviations/ (source recorded in dataset); Ollama, docs.ollama.com/api/chat. Full responses and model digests remain in results/runs/.",
        "BodyTiny",
    )

    doc = SimpleDocTemplate(
        str(target / "report.pdf"),
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=30,
        bottomMargin=30,
    )

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(555, 17, f"CS496 | {doc.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)

    if target == ROOT:
        readme = ROOT / "README.md"
        if readme.exists():
            text = readme.read_text(encoding="utf-8")
            start, end = "<!-- RESULTS_START -->", "<!-- RESULTS_END -->"
            a, b = text.split(start)
            _, c = b.split(end)
            readme.write_text(
                a
                + start
                + "\n\nRun: `"
                + meta["started_utc"]
                + "`\n\n"
                + table_markdown(summary)
                + "\n\n"
                + decision
                + "\n\n"
                + end
                + c,
                encoding="utf-8",
            )
    print("Generated", target / "report.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Regenerate the report from saved evidence; no model calls."
    )
    parser.add_argument(
        "--run",
        type=Path,
        help="Saved test run directory (default: latest published run)",
    )
    args = parser.parse_args()
    latest = (
        (ROOT / "results/latest_run.txt")
        .read_text(encoding="utf-8")
        .strip()
        .replace("\\", "/")
    )
    generate(args.run or ROOT / latest, publish=True)
