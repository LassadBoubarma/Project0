"""Build tables and a two-page PDF directly from the unchanged per-item CSV."""
import argparse
import csv
import json
import shutil
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from src.run import ROOT, FIELDS, read_json
from src.cost import percentile, local_scenario

SUMMARY_FIELDS=['role','model','n','correct','accuracy','parse_errors','refusals','timeouts','other_errors',
                'p50_ms','p95_ms','mean_ms','cost_per_1k_usd','cost_status','local_generation_tokens_per_second']


def summarise(rows, cfg):
    results=[]
    for model in cfg['models']:
        batch=[r for r in rows if r['role']==model['role']]
        if not batch:continue
        n=len(batch);times=[float(r['latency_ms']) for r in batch]
        item={'role':model['role'],'model':model['model'],'n':n,
              'correct':sum(int(r['correct']) for r in batch),
              'parse_errors':sum(r['status']=='parse_error' for r in batch),
              'refusals':sum(r['status']=='refusal' for r in batch),
              'timeouts':sum(r['status']=='timeout' for r in batch),
              'other_errors':sum(r['status'] not in {'correct','wrong_answer','parse_error','refusal','timeout'} for r in batch),
              'p50_ms':percentile(times,.5),'p95_ms':percentile(times,.95),'mean_ms':sum(times)/n,
              'cost_per_1k_usd':'','cost_status':'','local_generation_tokens_per_second':''}
        item['accuracy']=item['correct']/n
        if model['provider']=='gemini':
            costs=[r['api_cost_usd'] for r in batch]
            if all(c not in ('',None) for c in costs):
                item['cost_per_1k_usd']=1000*sum(float(c) for c in costs)/n
                item['cost_status']='complete usage; standard list price'
            else:
                item['cost_status']='unknown: one or more requests lack usage; see raw responses'
        else:
            durations=sum(float(r['eval_duration_ns'] or 0) for r in batch)/1e9
            tokens=sum(int(r['eval_count'] or 0) for r in batch)
            item['local_generation_tokens_per_second']=tokens/durations if durations else ''
            scenario=local_scenario(item['mean_ms']/1000,cfg['local_cost'])
            item['cost_per_1k_usd']=scenario.get('cost_per_1k_usd','')
            item['cost_status']=scenario['status']
        results.append(item)
    return results


def write_csv(path, fields, rows):
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def fmt(x, places=2):
    return 'pending' if x in ('',None) else f'{float(x):.{places}f}'


def table_markdown(summary):
    lines=['| Model | Correct | Accuracy | p50 ms | p95 ms | USD / 1k | Parse | Refusal | Timeout | Other |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in summary:
        lines.append(f"| {s['model']} | {s['correct']}/{s['n']} | {s['accuracy']:.1%} | {s['p50_ms']:.0f} | {s['p95_ms']:.0f} | {fmt(s['cost_per_1k_usd'],4)} | {s['parse_errors']} | {s['refusals']} | {s['timeouts']} | {s['other_errors']} |")
    if not summary:lines.append('| Real benchmark not yet run | pending | pending | pending | pending | pending | pending | pending | pending | pending |')
    return '\n'.join(lines)


def generate(run_dir=None, publish=False):
    cfg=read_json(ROOT/'config.json');rows=[];meta={};summary=[]
    target=ROOT if run_dir is None or publish else run_dir
    if run_dir:
        meta=read_json(run_dir/'metadata.json');cfg=meta['settings']
        if not meta.get('complete'):raise ValueError('Cannot report an interrupted run as complete.')
        with (run_dir/'per_item.csv').open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
        for m in cfg['models']:
            ids=[r['item_id'] for r in rows if r['role']==m['role']]
            if ids!=meta['item_ids']:raise ValueError('Missing, duplicated or reordered items.')
        summary=summarise(rows,cfg)
        write_csv(run_dir/'summary.csv',SUMMARY_FIELDS,summary)
        if publish:
            if meta['split']!='test' or len(meta['item_ids'])<50:raise ValueError('Only a full test run can be published.')
            shutil.copyfile(run_dir/'per_item.csv',ROOT/'results/per_item.csv')
            shutil.copyfile(run_dir/'summary.csv',ROOT/'results/summary.csv')
            (ROOT/'results/latest_run.txt').write_text(str(run_dir.relative_to(ROOT))+'\n')
    else:
        write_csv(ROOT/'results/per_item.csv',FIELDS,[])
        write_csv(ROOT/'results/summary.csv',SUMMARY_FIELDS,[])
    comparison=[]
    local=next((s for s in summary if s['role']=='local'),None)
    if local:
        for s in summary:
            if s['role']=='local':continue
            c=s['cost_per_1k_usd']
            scenario=local_scenario(local['mean_ms']/1000,cfg['local_cost'],None if c=='' else c/1000)
            comparison.append({'api_model':s['model'],'api_today_usd':None if c=='' else c*cfg['local_cost']['requests_per_month']/1000,
                               'api_100x_usd':None if c=='' else c*cfg['local_cost']['requests_per_month']/10,**scenario})
    (target/'cost_scenarios.json').write_text(json.dumps(comparison,indent=2)+'\n')
    failures=[]
    for m in cfg['models']:
        bad=[r for r in rows if r['role']==m['role'] and int(r['correct'])==0]
        failures.append((m,bad[:3],len(bad)))
    md=['# Error analysis','First three failures in original order. Full output remains in per_item.csv.']
    for m,bad,total in failures:
        md += ['\n## '+m['model'],f'{total} failures observed.' if rows else 'Not measured.']
        for r in bad:md.append(f"- {r['item_id']} ({r['abbreviation']}), {r['status']}: expected `{r['expected']}`; raw output {json.dumps(r['output'])}")
        if rows and total<3:md.append('Fewer than three failures exist; none invented.')
    (target/'error_analysis.md').write_text('\n'.join(md)+'\n')
    status='DRAFT - real benchmark not run' if not rows else ('DEV ONLY - excluded from final results' if meta['split']=='dev' else 'MEASURED - review decision, hardware and human notes before submission')
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodySmall',fontName='Helvetica',fontSize=9,leading=12,spaceAfter=7))
    styles.add(ParagraphStyle(name='CellSmall',fontName='Helvetica',fontSize=7,leading=9))
    story=[]
    def para(text,style='BodySmall'):story.append(Paragraph(escape(text),styles[style]))
    def heading(text):para(text,'Heading2')
    def grid(data,widths):
        cells=[[Paragraph(escape(str(c)),styles['CellSmall']) for c in row] for row in data]
        t=Table(cells,colWidths=widths,hAlign='LEFT');t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dbeafe')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('GRID',(0,0),(-1,-1),.35,colors.HexColor('#cbd5e1')),('LEFTPADDING',(0,0),(-1,-1),5),
            ('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        story.append(t);story.append(Spacer(1,8))
    para('Medical abbreviation bake-off','Title');para('CS496 Project 0 | '+status)
    heading('1. Task and data')
    para('Expand one abbreviation in a short UK medical-record context. Example: "The nurse recorded BP before the consultation." Expected: blood pressure. Choose one exact string from a fixed 60-term output vocabulary. Correct answers are stored separately and never supplied with questions.')
    para('50 test items and 10 development items, with disjoint abbreviations. Factual expansions: NHS glossary; contexts: original synthetic sentences drafted with AI assistance. Parenthetical explanations are omitted and canonical case is fixed. Two people must independently check every label in data/label_reviews.csv; review is pending in the supplied draft. No patient records are used.')
    heading('2. Experiment')
    for m in cfg['models']:para(m['role']+': '+m['model'])
    para(f"Same literal prompt, vocabulary, question order, parser, temperature 0 and output limit {cfg['max_output_tokens']} for all models. One call per item; sequential requests; no retries, retrieval, tools or chat history. Native tokenisers and internal reasoning defaults differ. Blank, non-vocabulary, extra-text or multiline outputs fail parsing; outer whitespace alone is ignored. Refusals, timeouts, truncation and API failures count as wrong.")
    para('Wall-clock latency measures send to full response (all attempted calls, including errors and the first local cold load). p50/p95 use linear interpolation. Local generation speed uses total generated tokens / total generation time; it excludes prompt processing. Exact versions, UTC date and local model digest are saved in run metadata.')
    heading('3. Results')
    data=[['Model','Correct','p50 / p95 ms','USD / 1k','P / R / T / O']]
    for s in summary:data.append([s['model'],f"{s['correct']}/{s['n']} ({s['accuracy']:.0%})",f"{s['p50_ms']:.0f} / {s['p95_ms']:.0f}",fmt(s['cost_per_1k_usd'],4),f"{s['parse_errors']} / {s['refusals']} / {s['timeouts']} / {s['other_errors']}"])
    if not summary:data += [[m['model'],'pending','pending','pending','pending'] for m in cfg['models']]
    grid(data,[150,75,90,70,120])
    para('P=parse errors; R=refusals; T=timeouts; O=other execution errors. All remain in the accuracy denominator. Missing usage means unknown cost, never zero. Source: results/per_item.csv; no model measurements are included in the supplied draft.')
    story.append(PageBreak())
    para('Evidence, cost and decision','Title')
    heading('4. Wrong answers (first three per model)')
    for m,bad,total in failures:
        para(m['model']+' — '+(f'{total} failures' if rows else 'pending real run'))
        for r in bad:
            out=r['output'].replace('\n',' / ')
            if len(out)>110:out=out[:107]+'...'
            para(f"{r['item_id']} {r['abbreviation']}: expected {r['expected']}; output {out or '[empty]'} ({r['status']}).")
        if rows and total<3:para('Fewer than three failures; no additional examples invented.')
    heading('5. Cost, traffic and hardware')
    para('API cost = (uncached input × input rate + cached input × cache rate + visible and thinking output × output rate) / 1,000,000. Standard paid USD list prices, checked '+cfg['pricing_checked']+'. Local cost = hardware USD/hour ÷ measured requests/hour plus monthly operator labour divided by volume. Hardware hourly rate must include depreciation/rental and electricity; assumptions remain user-supplied.')
    if comparison:
        for c in comparison:
            para(f"{c['api_model']}: API today ${fmt(c['api_today_usd'],3)}; 100x ${fmt(c['api_100x_usd'],3)}. Local today ${fmt(c.get('today_usd'),3)}; 100x ${fmt(c.get('100x_usd'),3)}. Break-even requests/month: {fmt(c.get('break_even_requests_per_month'),0)}.")
    else:para('Today: 1,000 requests/month; 100x: 100,000. Numeric totals and break-even are pending measurements and real hardware/labour assumptions. Break-even V = fixed monthly labour / (API cost/request - local variable cost/request), only when the denominator is positive. Validate against one-machine capacity before interpreting it.')
    if local:para('Local generation tokens/second: '+fmt(local['local_generation_tokens_per_second'])+'. See results/hardware.md and run metadata for CPU/GPU/RAM and quantisation. Scenario capacity and feasibility are in cost_scenarios.json.')
    else:para('Hardware: pending your PC specifications, RAM, GPU/VRAM and Ollama version. Default local model: Qwen2.5 1.5B, Q4_K_M (record actual digest and quantisation during the run).')
    heading('6. Choice and limitations')
    decision=(ROOT/'decision.txt').read_text(encoding='utf-8').strip()
    para(decision)
    para('A vocabulary-constrained benchmark measures canonical matching, not clinical competence. Contexts may make the task easy. If development results saturate, revise the task before freezing; never remove failed test items. With only 50 test cases, one item changes accuracy by two percentage points. Exact-match failures can reflect formatting rather than knowledge.')
    para('Sources: NHS, nhs.uk/nhs-app/help/understanding-abbreviations/; Google, ai.google.dev/gemini-api/docs/pricing and /models; Ollama, ollama.com/library/qwen2.5:1.5b. Full URLs and methodology: data/labelling_note.md and README.md.')
    doc=SimpleDocTemplate(str(target/'report.pdf'),pagesize=A4,rightMargin=40,leftMargin=40,topMargin=30,bottomMargin=30)
    def footer(canvas,doc):
        canvas.setFont('Helvetica',8);canvas.drawRightString(555,17,f'CS496 | {doc.page}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    (target/'results_table.md').write_text(table_markdown(summary)+'\n')
    if target==ROOT:
        readme=ROOT/'README.md'
        if readme.exists():
            text=readme.read_text();start='<!-- RESULTS_START -->';end='<!-- RESULTS_END -->'
            a,b=text.split(start);_,c=b.split(end)
            readme.write_text(a+start+'\n'+table_markdown(summary)+'\n'+end+c)
    print('Generated',target/'report.pdf')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path);p.add_argument('--draft',action='store_true');a=p.parse_args()
    if a.draft:generate()
    else:
        path=a.run or ROOT/(ROOT/'results/latest_run.txt').read_text().strip()
        generate(path,publish=True)
