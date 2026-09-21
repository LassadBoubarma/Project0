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

from src.run import ROOT, read_json
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


def audit_normalization(rows, models):
    """Post-run diagnostics only. Never alter scores or saved model answers."""

    def spelling_key(text):
        text = text.strip().casefold()
        for before, after in [
            ("haem", "hem"),
            ("faec", "fec"),
            ("normalised", "normalized"),
        ]:
            text = text.replace(before, after)
        return "".join(text.split()).replace("-", "")

    findings = []
    for model in models:
        batch = [r for r in rows if r["role"] == model["role"]]
        failures = [r for r in batch if r["correct"] == "0"]
        candidates = [
            r
            for r in failures
            if spelling_key(r["output"]) == spelling_key(r["expected"])
        ]
        findings.append(
            {
                "model": model["model"],
                "strict": sum(r["output"].strip() == r["expected"] for r in batch),
                "accepted": sum(int(r["correct"]) for r in batch),
                "failures": len(failures),
                "candidates": candidates,
            }
        )
    return findings


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

    audit = audit_normalization(rows, cfg["models"])
    hw = meta["hardware"]
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            fontName="Helvetica-Bold",
            fontSize=21,
            leading=24,
            textColor=colors.HexColor("#15384b"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#087e83"),
            spaceBefore=10,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodySmall",
            fontName="Helvetica",
            fontSize=9,
            leading=11.5,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyTiny", fontName="Helvetica", fontSize=8, leading=10, spaceAfter=5
        )
    )
    styles.add(
        ParagraphStyle(
            name="CellSmall", fontName="Helvetica", fontSize=7.6, leading=9.5
        )
    )
    story = []

    def para(text, style="BodySmall"):
        story.append(Paragraph(escape(text), styles[style]))

    def heading(text):
        para(text, "Section")

    def grid(data, widths):
        cells = [
            [Paragraph(escape(str(c)), styles["CellSmall"]) for c in row]
            for row in data
        ]
        table = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#deedef")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f5f8fa")],
                    ),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#087e83")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 6))

    para("Medical abbreviation bake-off", "ReportTitle")
    para(
        "CS496 AI Engineering | Project 0 | Mediterranean Institute of Technology",
        "BodyTiny",
    )
    para(
        "Measured run: " + meta["started_utc"] + " UTC | " + meta["split"].upper(),
        "BodyTiny",
    )
    para(
        "Scope: three local Qwen sizes, selected to avoid paid API usage. This adapts the required top-API / cheap-API / local comparison; instructor acceptance remains to be confirmed.",
        "BodyTiny",
    )

    heading("01  Task and dataset")
    example = read_json(run_dir / "items.json")[0]
    para(
        "Expand an abbreviation from a short UK medical-record context into one canonical term. One model call produces one answer; a deterministic function scores it without a human or LLM judge."
    )
    para(
        f"Example: {example['context']} Asked: {example['abbreviation']}. Gold answer: {example['expected']}."
    )
    para(
        "The project contains 50 test and 10 development items with disjoint abbreviations. Labels follow the NHS glossary [1]; contexts were synthetically drafted with AI assistance and contain no patient data. The fixed convenience split puts familiar terms in dev and rarer terms in test. It is not a random sample. The review CSV records Lassaad and Rami for all 60 labels, dated 11 September 2026."
    )

    heading("02  Reproducible setup")
    para(
        "Models: "
        + ", ".join(m["model"] for m in cfg["models"])
        + f". Ollama {hw.get('ollama_version', {}).get('version', 'unrecorded')}; Q4_K_M quantization in the saved model metadata. Hardware: {hw.get('cpu')}; {hw.get('gpu')}; {hw.get('ram_gb')} GB RAM; Python {hw.get('python')}."
    )
    para(
        f"Shared settings: temperature {cfg['temperature']}, output limit {cfg['max_output_tokens']} tokens, context window 8192, timeout {cfg['timeout_seconds']} s. Identical item order, prompt and parser; sequential requests, no retries, retrieval, tools or chat history. Gold labels and vocabulary are hidden from the models."
    )
    para(
        "Prompt instruction: Expand the medical abbreviation in the supplied UK medical-record context. Return ONLY the full medical term on one line. No abbreviation, explanation, quotes, JSON, Answer: label or final full stop. Use the standard UK expansion indicated by context. Full exact prompts are saved with the run.",
        "BodyTiny",
    )

    heading("03  Results from all 150 attempts")
    table = [
        [
            "Model",
            "Correct / accuracy",
            "p50 / p95 ms",
            "USD / 1k",
            "Tokens/s",
            "P / R / T / O",
        ]
    ]
    for s in summary:
        table.append(
            [
                s["model"],
                f"{s['correct']}/{s['n']} ({s['accuracy']:.0%})",
                f"{s['p50_ms']:.0f} / {s['p95_ms']:.0f}",
                fmt(s["cost_per_1k_usd"], 4),
                fmt(s["local_generation_tokens_per_second"], 1),
                f"{s['parse_errors']} / {s['refusals']} / {s['timeouts']} / {s['other_errors']}",
            ]
        )
    grid(table, [90, 85, 83, 65, 58, 130])
    para(
        "P=parse, R=refusal, T=timeout, O=other execution errors. Wrong in-vocabulary answers remain in the accuracy denominator; P includes out-of-vocabulary wording, not just broken formatting. Explicit refusal prefixes are detected; other refusal wording can remain P. All failures count as wrong.",
        "BodyTiny",
    )
    para(
        "Latency is full request wall time, including any loading; pacing pauses are excluded. p50/p95 use linear interpolation over all attempts. Tokens/s = total generation tokens / total generation seconds from Ollama [2], not end-to-end throughput.",
        "BodyTiny",
    )

    heading("04  Normalization and false-negative audit")
    para(
        "The scorer trims outer whitespace and case-folds both answer and label, then requires exact wording and one line. On these same responses, case-sensitive matching would accept "
        + "/".join(str(a["strict"]) for a in audit)
        + "; the frozen normalized scorer accepts "
        + "/".join(str(a["accepted"]) for a in audit)
        + " (small/medium/large). This is a diagnostic comparison, not a new model run."
    )
    para(
        "All "
        + str(sum(a["failures"] for a in audit))
        + " failed responses were checked in a mechanical spelling audit. "
        + str(sum(len(a["candidates"]) for a in audit))
        + " are spelling/spacing/hyphen candidates. They remain wrong under the frozen rule; the audit does not certify clinical equivalence or change accuracy.",
        "BodyTiny",
    )

    story.append(PageBreak())
    para("Errors, decision and cost", "ReportTitle")
    heading("05  Three recorded wrong answers per model")
    table = [["Model / item", "Expected", "Actual response"]]
    for model, bad, total in failures:
        for row in bad:
            table.append(
                [
                    model["model"] + " / " + row["abbreviation"],
                    row["expected"],
                    row["output"][:140] or "[empty]",
                ]
            )
    grid(table, [100, 175, 236])
    para(
        "First three failures per model in recorded order; all nine are parse_error under the vocabulary policy. Full outputs and all remaining errors are in results/per_item.csv.",
        "BodyTiny",
    )

    heading("06  What the errors mean")
    para(
        "Capitalization alone is now accepted: Activated Partial Thromboplastin Time matches its lower-case label. Fecal versus faecal and High Density versus high-density are candidates for a future spelling policy. Investigation versus investigations is a singular/plural difference. Physiotherapy versus physiotherapist changes an activity into a professional role; blindly stemming words would conceal such distinctions."
    )
    para(
        "Early dev prompts exposed the vocabulary and produced 10/10 scores. The final task hides it, so those pilots are not directly comparable. A case-sensitive 150-call run on 13 September accepted only 3 answers; a later full rerun used normalization. The archived 14 September run reproduced all 150 previous raw answer strings, but latency changed. These repeated items do not constitute 300 independent test examples.",
        "BodyTiny",
    )

    heading("07  Model choice and switching conditions")
    para(decision)
    para(
        "Use the highest-accuracy model only as the benchmark preference, not as a clinical deployment recommendation. The 95% accuracy and p95 below 10 s thresholds are project decision rules, not course requirements; preregistration is not established. Switch to a smaller model if it meets those targets at lower cost on a new frozen set. Re-evaluate if hardware, traffic or wording policy changes.",
        "BodyTiny",
    )

    heading("08  Cost today, at 100x, and break-even")
    cost = cfg["local_cost"]
    para(
        f"No API fees. Assumptions: ${cost['hardware_usd_per_hour']}/active hardware hour, {cost['labour_hours_per_month']} labour hour/month at ${cost['labour_usd_per_hour']}/hour, {cost['available_hours_per_month']} available hours/month. Baseline {cost['requests_per_month']:,} requests; 100x {100 * cost['requests_per_month']:,}. These are estimates, not measured invoices.",
        "BodyTiny",
    )
    table = [["Model", "Baseline USD/mo", "100x USD/mo", "Capacity requests/mo"]]
    for sc in scenarios:
        table.append(
            [
                sc["model"],
                fmt(sc["today_usd"], 3),
                fmt(sc["100x_usd"], 3),
                fmt(sc["capacity_per_month"], 0),
            ]
        )
    grid(table, [105, 125, 125, 156])
    para(
        "For mean request seconds s: throughput = 3600/s; variable cost v = hardware hourly rate / throughput; monthly cost = labour F + volume N*v. Each candidate is an alternative deployment. For this measured run, the capacity table supports 100x under these assumptions; pauses, always-on rental and scaling overhead are excluded. Throughput and labour are assumed unchanged.",
        "BodyTiny",
    )
    para(
        "API/local break-even would be N = F/(A-v), where A is API cost/request, only when A>v and capacity permits. With no measured API comparator, a numerical break-even cannot be claimed. Instructor approval is needed for this omission.",
        "BodyTiny",
    )
    para(
        "Limits: one model family, one machine, 50 synthetic test items (one item = 2 percentage points), and exact canonical wording. No statistical significance or clinical competence is established.",
        "BodyTiny",
    )
    para(
        "[1] NHS: nhs.uk/nhs-app/help/understanding-abbreviations/ (checked 14 Sep 2026). [2] Ollama: docs.ollama.com/api/chat. Run metadata, raw responses and hashes: results/runs/.",
        "BodyTiny",
    )

    doc = SimpleDocTemplate(
        str(target / "report.pdf"),
        pagesize=A4,
        leftMargin=42,
        rightMargin=42,
        topMargin=30,
        bottomMargin=32,
    )

    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor("#bdd3d8"))
        canvas.line(42, 25, 553, 25)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(
            42, 14, "CS496 | Medical abbreviation bake-off | Local-only adaptation"
        )
        canvas.drawRightString(553, 14, str(doc.page))

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
