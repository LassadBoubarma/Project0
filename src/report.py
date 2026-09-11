"""Build final tables, evidence notes and the two-page report from one unchanged run CSV."""
import argparse
import csv
import json
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.run import ROOT, FIELDS, load_data, read_json, reviews_ready
from src.cost import percentile, local_scenario

SUMMARY_FIELDS = [
    'role','model','n','correct','accuracy','parse_errors','refusals','timeouts','other_errors',
    'p50_ms','p95_ms','mean_ms','cost_per_1k_usd','cost_status','local_generation_tokens_per_second'
]


def summarise(rows, cfg):
    results = []
    for model in cfg['models']:
        batch = [r for r in rows if r['role'] == model['role']]
        if not batch:
            continue
        n = len(batch)
        times = [float(r['latency_ms']) for r in batch]
        item = {
            'role': model['role'], 'model': model['model'], 'n': n,
            'correct': sum(int(r['correct']) for r in batch),
            'parse_errors': sum(r['status'] == 'parse_error' for r in batch),
            'refusals': sum(r['status'] == 'refusal' for r in batch),
            'timeouts': sum(r['status'] == 'timeout' for r in batch),
            'other_errors': sum(
                r['status'] not in {'correct','wrong_answer','parse_error','refusal','timeout'}
                for r in batch
            ),
            'p50_ms': percentile(times, .5), 'p95_ms': percentile(times, .95),
            'mean_ms': sum(times) / n, 'cost_per_1k_usd': '', 'cost_status': '',
            'local_generation_tokens_per_second': ''
        }
        item['accuracy'] = item['correct'] / n
        if model['provider'] != 'ollama':
            costs = [r['api_cost_usd'] for r in batch]
            if all(c not in ('', None) for c in costs):
                item['cost_per_1k_usd'] = 1000 * sum(float(c) for c in costs) / n
                item['cost_status'] = 'complete usage; standard list price'
            else:
                item['cost_status'] = 'unknown: one or more requests lack usage'
        else:
            durations = sum(float(r['eval_duration_ns'] or 0) for r in batch) / 1e9
            tokens = sum(int(r['eval_count'] or 0) for r in batch)
            item['local_generation_tokens_per_second'] = tokens / durations if durations else ''
            scenario = local_scenario(item['mean_ms'] / 1000, cfg['local_cost'])
            item['cost_per_1k_usd'] = scenario.get('cost_per_1k_usd', '')
            item['cost_status'] = scenario['status']
        results.append(item)
    return results


def write_csv(path, fields, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fmt(x, places=2):
    return 'pending' if x in ('', None) else f'{float(x):.{places}f}'


def table_markdown(summary):
    lines = [
        '| Model | Correct | Accuracy | p50 ms | p95 ms | USD / 1k | Parse | Refusal | Timeout | Other |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|'
    ]
    for s in summary:
        lines.append(
            f"| {s['model']} | {s['correct']}/{s['n']} | {s['accuracy']:.1%} | "
            f"{s['p50_ms']:.0f} | {s['p95_ms']:.0f} | {fmt(s['cost_per_1k_usd'],4)} | "
            f"{s['parse_errors']} | {s['refusals']} | {s['timeouts']} | {s['other_errors']} |"
        )
    if not summary:
        lines.append('| Real benchmark not yet run | pending | pending | pending | pending | pending | pending | pending | pending | pending |')
    return '\n'.join(lines)


def build_decision(summary):
    if not summary:
        return ('Decision pending real results. Predeclared rule: choose the lowest-cost model reaching at least '
                '95% exact-match accuracy and p95 below 10 seconds; if none qualifies, report that none meets the target.')
    eligible = [
        s for s in summary
        if s['accuracy'] >= .95 and s['p95_ms'] < 10_000 and s['cost_per_1k_usd'] not in ('', None)
    ]
    if eligible:
        chosen = min(eligible, key=lambda s: (float(s['cost_per_1k_usd']), -s['accuracy'], s['p95_ms']))
        return (
            f"Choice: {chosen['model']}. It satisfies the predeclared target with "
            f"{chosen['correct']}/{chosen['n']} correct ({chosen['accuracy']:.1%}), p95 latency "
            f"{chosen['p95_ms']:.0f} ms and estimated cost ${float(chosen['cost_per_1k_usd']):.4f} per 1,000 requests. "
            "Among models meeting both quality and latency thresholds, it has the lowest measured/estimated cost. "
            "We would change the choice if its accuracy falls below 95%, p95 rises above 10 seconds, pricing or hardware "
            "cost changes materially, or traffic crosses a feasible API/local break-even point."
        )
    best = max(summary, key=lambda s: (s['accuracy'], -s['p95_ms']))
    return (
        "Choice: none of the three models meets the full predeclared acceptance rule (at least 95% exact-match accuracy, "
        "p95 below 10 seconds, and known cost). The strongest measured accuracy is "
        f"{best['model']} at {best['correct']}/{best['n']} ({best['accuracy']:.1%}) with p95 {best['p95_ms']:.0f} ms. "
        "We would reconsider after improving the failing requirement or if deployment constraints change."
    )


def build_postmortem(summary, rows):
    if not summary or not rows:
        return ("# Postmortem - draft\n\nReal benchmark not run yet. Complete the final test first; the final runner "
                "will replace this draft using observed evidence.\n")
    failures = [r for r in rows if int(r['correct']) == 0]
    fastest = min(summary, key=lambda s: s['p95_ms'])
    most_accurate = max(summary, key=lambda s: (s['accuracy'], -s['p95_ms']))
    known_cost = [s for s in summary if s['cost_per_1k_usd'] not in ('', None)]
    cheapest = min(known_cost, key=lambda s: float(s['cost_per_1k_usd'])) if known_cost else None

    if failures:
        first = failures[0]
        problem = (
            f"The final benchmark produced {len(failures)} incorrect/failed responses across all models. "
            f"The first observed failure was {first['role']} on {first['item_id']} ({first['abbreviation']}): "
            f"status `{first['status']}`, expected `{first['expected']}`, raw output {json.dumps(first['output'])}. "
            "The failed row was kept in the denominator and archived; nothing was repaired by hand."
        )
        improvement = (
            "A next version should create a separately versioned test set that targets the observed failure types while "
            "keeping the original frozen run unchanged. If formatting failures dominate, the new benchmark could report "
            "semantic and strict-format scores separately rather than retroactively loosening this scorer."
        )
    else:
        problem = (
            "All three models completed the frozen test without a wrong answer. This is itself an evaluation problem: "
            "the benchmark is saturated, so accuracy cannot distinguish model capability even though latency and cost still can. "
            "The 50-item results were kept exactly as measured rather than making the test harder after seeing them."
        )
        improvement = (
            "A follow-up should use a separately versioned harder set with more ambiguous-but-context-resolved abbreviations "
            "and no overlap with this test. The original 50 items must remain archived because editing them after seeing the "
            "outputs would invalidate the comparison."
        )

    cheapest_text = (
        f"The lowest cost/1,000 is {cheapest['model']} at ${float(cheapest['cost_per_1k_usd']):.4f}. "
        if cheapest else "One or more cost values were unavailable, so a complete cost ranking was not possible. "
    )
    return f'''# Postmortem

## What went wrong / limitation observed

{problem}

## What we learned

The highest measured accuracy was **{most_accurate['model']}** at **{most_accurate['correct']}/{most_accurate['n']} ({most_accurate['accuracy']:.1%})**. The fastest p95 was **{fastest['model']}** at **{fastest['p95_ms']:.0f} ms**. {cheapest_text}This demonstrates why the project needs accuracy, tail latency and cost together rather than a single "winner" score.

## What we would improve

{improvement} With only 50 final items, one answer moves accuracy by two percentage points, so the result should not be treated as a clinical-safety claim or a universal estimate of model quality.
'''


def write_hardware_note(path, meta, cfg, summary):
    hw = meta.get('hardware', {})
    model_record = hw.get('model', {})
    details = model_record.get('details', {}) if isinstance(model_record, dict) else {}
    local = next((s for s in summary if s['role'] == 'local'), None)
    cost = cfg.get('local_cost', {})
    lines = [
        '# Local hardware and self-hosting assumptions', '',
        'Captured during the final run; no GPU/CPU value below is intentionally guessed.', '',
        f"- Operating system: {hw.get('os') or 'not detected'}",
        f"- CPU: {hw.get('cpu') or 'not detected'}",
        f"- GPU: {hw.get('gpu') or 'not detected / CPU-only not confirmed'}",
        f"- RAM: {str(hw.get('ram_gb')) + ' GB' if hw.get('ram_gb') not in ('',None) else 'not detected'}",
        f"- Python: {hw.get('python') or 'not detected'}",
        f"- Ollama version: {json.dumps(hw.get('ollama_version', {}), ensure_ascii=False)}",
        f"- Local model: {model_record.get('name', 'qwen2.5:1.5b') if isinstance(model_record, dict) else 'qwen2.5:1.5b'}",
        f"- Model digest: {model_record.get('digest', 'not detected') if isinstance(model_record, dict) else 'not detected'}",
        f"- Parameter size: {details.get('parameter_size', 'not detected')}",
        f"- Quantisation: {details.get('quantization_level', 'not detected')}",
        f"- Generation tokens/second: {fmt(local.get('local_generation_tokens_per_second') if local else None)}",
        '', 'Cost assumptions from config.json:',
        f"- Hardware + electricity: ${cost.get('hardware_usd_per_hour')} per hour",
        f"- Operator time: {cost.get('labour_hours_per_month')} hours/month at ${cost.get('labour_usd_per_hour')}/hour",
        f"- Baseline traffic: {cost.get('requests_per_month')} requests/month",
        f"- Available serving time: {cost.get('available_hours_per_month')} hours/month",
        '',
        'If these assumptions change, rerun report generation before submission because local cost and break-even change.'
    ]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def generate(run_dir=None, publish=False):
    cfg = read_json(ROOT / 'config.json')
    rows, meta, summary = [], {}, []
    target = ROOT if run_dir is None or publish else run_dir

    if run_dir:
        meta = read_json(run_dir / 'metadata.json')
        cfg = meta['settings']
        if not meta.get('complete'):
            raise ValueError('Cannot report an interrupted run as complete.')
        with (run_dir / 'per_item.csv').open(encoding='utf-8', newline='') as f:
            rows = list(csv.DictReader(f))
        for m in cfg['models']:
            ids = [r['item_id'] for r in rows if r['role'] == m['role']]
            if ids != meta['item_ids']:
                raise ValueError('Missing, duplicated or reordered items.')
        summary = summarise(rows, cfg)
        write_csv(run_dir / 'summary.csv', SUMMARY_FIELDS, summary)
        if publish:
            if meta['split'] != 'test' or len(meta['item_ids']) < 50:
                raise ValueError('Only a full test run can be published.')
            shutil.copyfile(run_dir / 'per_item.csv', ROOT / 'results/per_item.csv')
            shutil.copyfile(run_dir / 'summary.csv', ROOT / 'results/summary.csv')
            (ROOT / 'results/latest_run.txt').write_text(str(run_dir.relative_to(ROOT)) + '\n', encoding='utf-8')
    else:
        write_csv(ROOT / 'results/per_item.csv', FIELDS, [])
        write_csv(ROOT / 'results/summary.csv', SUMMARY_FIELDS, [])

    comparison = []
    local = next((s for s in summary if s['role'] == 'local'), None)
    if local:
        for s in summary:
            if s['role'] == 'local':
                continue
            c = s['cost_per_1k_usd']
            scenario = local_scenario(local['mean_ms']/1000, cfg['local_cost'], None if c == '' else c/1000)
            comparison.append({
                'api_model': s['model'],
                'api_today_usd': None if c == '' else c * cfg['local_cost']['requests_per_month']/1000,
                'api_100x_usd': None if c == '' else c * cfg['local_cost']['requests_per_month']/10,
                **scenario
            })
    (target / 'cost_scenarios.json').write_text(json.dumps(comparison, indent=2) + '\n', encoding='utf-8')

    failures = []
    for m in cfg['models']:
        bad = [r for r in rows if r['role'] == m['role'] and int(r['correct']) == 0]
        failures.append((m, bad[:3], len(bad)))
    md = ['# Error analysis', 'First three failures in original order. Full output remains in per_item.csv.']
    for m, bad, total in failures:
        md += ['\n## ' + m['model'], f'{total} failures observed.' if rows else 'Not measured.']
        for r in bad:
            md.append(
                f"- {r['item_id']} ({r['abbreviation']}), {r['status']}: expected `{r['expected']}`; "
                f"raw output {json.dumps(r['output'])}"
            )
        if rows and total < 3:
            md.append('Fewer than three failures exist; none invented.')
    (target / 'error_analysis.md').write_text('\n'.join(md) + '\n', encoding='utf-8')

    decision = build_decision(summary)
    if publish or not rows:
        (target / 'decision.txt').write_text(decision + '\n', encoding='utf-8')
    if publish:
        (ROOT / 'postmortem.md').write_text(build_postmortem(summary, rows), encoding='utf-8')
        write_hardware_note(ROOT / 'results/hardware.md', meta, cfg, summary)

    status = (
        'DRAFT - real benchmark not run' if not rows else
        ('DEV ONLY - excluded from final results' if meta['split'] == 'dev' else 'MEASURED FINAL TEST')
    )
    review_complete = False
    try:
        review_complete = reviews_ready(load_data('test')[0])
    except (OSError, KeyError, ValueError):
        pass

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodySmall', fontName='Helvetica', fontSize=9, leading=12, spaceAfter=7))
    styles.add(ParagraphStyle(name='CellSmall', fontName='Helvetica', fontSize=7, leading=9))
    story = []

    def para(text, style='BodySmall'):
        story.append(Paragraph(escape(text), styles[style]))

    def heading(text):
        para(text, 'Heading2')

    def grid(data, widths):
        cells = [[Paragraph(escape(str(c)), styles['CellSmall']) for c in row] for row in data]
        table = Table(cells, colWidths=widths, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dbeafe')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('GRID',(0,0),(-1,-1),.35,colors.HexColor('#cbd5e1')),
            ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
            ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)
        ]))
        story.append(table)
        story.append(Spacer(1, 8))

    para('Medical abbreviation bake-off', 'Title')
    para('CS496 Project 0 | ' + status)
    heading('1. Task and data')
    para('Expand one abbreviation in a short UK medical-record context. Example: "The nurse recorded BP before the consultation." Expected: blood pressure. The prompt supplies a fixed 60-term output vocabulary but never supplies the abbreviation-to-answer mapping.')
    review_text = 'complete' if review_complete else 'pending'
    para(f'50 frozen test items and 10 development items use disjoint abbreviations. Factual expansions come from the NHS glossary; contexts are original synthetic sentences and contain no patient data. Two-person human label review status: {review_text}.')

    heading('2. Experiment')
    for m in cfg['models']:
        para(m['role'] + ': ' + m['model'])
    para(f"Same literal prompt, vocabulary, question order, parser, temperature 0 and output limit {cfg['max_output_tokens']} for all models. One call per item; sequential requests; no retries, retrieval, tools or chat history. Blank, non-vocabulary, extra-text or multiline outputs fail parsing; outer whitespace alone is ignored. Refusals, timeouts, truncation and API failures count as wrong.")
    para('Latency is wall time from send to full response for every attempt; p50/p95 use linear interpolation. The first local cold load is included. Local generation tokens/second excludes prompt processing. Exact model/version, UTC date, file hashes and local model digest are saved in run metadata.')

    heading('3. Results')
    data = [['Model','Correct','p50 / p95 ms','USD / 1k','P / R / T / O']]
    for s in summary:
        data.append([
            s['model'], f"{s['correct']}/{s['n']} ({s['accuracy']:.0%})",
            f"{s['p50_ms']:.0f} / {s['p95_ms']:.0f}", fmt(s['cost_per_1k_usd'],4),
            f"{s['parse_errors']} / {s['refusals']} / {s['timeouts']} / {s['other_errors']}"
        ])
    if not summary:
        data += [[m['model'],'pending','pending','pending','pending'] for m in cfg['models']]
    grid(data, [150,75,90,70,120])
    para('P=parse errors; R=refusals; T=timeouts; O=other execution errors. All remain in the accuracy denominator. Missing usage means unknown cost, never zero. Final numbers come directly from results/per_item.csv.')

    story.append(PageBreak())
    para('Evidence, cost and decision', 'Title')
    heading('4. Wrong answers (first three per model)')
    for m, bad, total in failures:
        para(m['model'] + ' - ' + (f'{total} failures' if rows else 'pending real run'))
        for r in bad:
            out = r['output'].replace('\n', ' / ')
            if len(out) > 110:
                out = out[:107] + '...'
            para(f"{r['item_id']} {r['abbreviation']}: expected {r['expected']}; output {out or '[empty]'} ({r['status']}).")
        if rows and total < 3:
            para('Fewer than three failures; no additional examples invented.')

    heading('5. Cost, traffic and hardware')
    para('API cost uses real usage token counts and paid standard USD list prices checked ' + cfg['pricing_checked'] + '. Local cost uses measured request throughput plus the hardware/electricity and operator-time assumptions in config.json. Baseline traffic is 1,000 requests/month and 100x traffic is 100,000/month.')
    if comparison:
        for c in comparison:
            para(f"{c['api_model']}: API today ${fmt(c['api_today_usd'],3)}; 100x ${fmt(c['api_100x_usd'],3)}. Local today ${fmt(c.get('today_usd'),3)}; 100x ${fmt(c.get('100x_usd'),3)}. Break-even requests/month: {fmt(c.get('break_even_requests_per_month'),0)}; one-machine fit: {c.get('break_even_fits_one_machine')}.")
    else:
        para('Numeric 100x and break-even values are pending the real run and user-supplied local cost assumptions. Break-even is only defined when the API variable cost exceeds the local variable cost.')
    if local:
        para('Local generation tokens/second: ' + fmt(local['local_generation_tokens_per_second']) + '. Exact detected hardware/model details and cost assumptions are in results/hardware.md and run metadata.')
    else:
        para('Hardware details and local cost are pending the final run on the student machine.')

    heading('6. Choice and limitations')
    para(decision)
    para('This vocabulary-constrained benchmark measures canonical matching, not clinical competence. The contexts and answer vocabulary may make the task easy. With 50 test cases, one item changes accuracy by two percentage points. Final test items must never be removed or repaired after seeing model outputs.')
    para('Sources: NHS abbreviation glossary; Google Gemini model/pricing documentation; Ollama Qwen2.5 model metadata. Full methodology and URLs are in data/labelling_note.md and README.md.')

    doc = SimpleDocTemplate(
        str(target / 'report.pdf'), pagesize=A4,
        rightMargin=40, leftMargin=40, topMargin=30, bottomMargin=30
    )

    def footer(canvas, doc):
        canvas.setFont('Helvetica', 8)
        canvas.drawRightString(555, 17, f'CS496 | {doc.page}')

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    (target / 'results_table.md').write_text(table_markdown(summary) + '\n', encoding='utf-8')

    if target == ROOT:
        readme = ROOT / 'README.md'
        if readme.exists():
            text = readme.read_text(encoding='utf-8')
            start, end = '<!-- RESULTS_START -->', '<!-- RESULTS_END -->'
            a, b = text.split(start)
            _, c = b.split(end)
            readme.write_text(a + start + '\n\n' + table_markdown(summary) + '\n\n' + end + c, encoding='utf-8')

    print('Generated', target / 'report.pdf')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path)
    parser.add_argument('--draft', action='store_true')
    args = parser.parse_args()
    if args.draft:
        generate()
    else:
        latest = ROOT / 'results/latest_run.txt'
        path = args.run or ROOT / latest.read_text(encoding='utf-8').strip()
        generate(path, publish=True)
