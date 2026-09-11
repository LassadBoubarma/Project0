"""Submission readiness check. It never edits results or makes paid model requests."""
import csv
import json
import os
import urllib.error
from pathlib import Path

from src.run import ROOT, api_key_for, load_data, local_cost_ready, read_json, request_json, reviews_ready


def row(label, ok, detail=''):
    mark = 'OK     ' if ok else 'PENDING'
    print(f'{mark}  {label}' + (f' - {detail}' if detail else ''))
    return ok


def final_results_ready(cfg):
    path = ROOT / 'results/summary.csv'
    if not path.exists():
        return False, 'summary.csv missing'
    with path.open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != len(cfg['models']):
        return False, 'final three-model summary not present'
    if any(int(r.get('n') or 0) < 50 for r in rows):
        return False, 'one or more models has fewer than 50 final items'
    if any(r.get('cost_per_1k_usd') in ('', None) for r in rows):
        return False, 'one or more final costs is missing'
    return True, '3 models x 50 items with costs'


def main():
    cfg = read_json(ROOT / 'config.json')
    test, _ = load_data('test')
    dev, _ = load_data('dev')
    checks = []

    checks.append(row('50+ frozen test items', len(test) >= 50, f'{len(test)} items'))
    checks.append(row('Separate development set', bool(dev) and not ({i['abbreviation'] for i in dev} & {i['abbreviation'] for i in test}), f'{len(dev)} items'))
    checks.append(row('Temperature is 0', cfg.get('temperature') == 0))
    checks.append(row('Two real reviewers on every test label', reviews_ready(test)))
    checks.append(row('Local hardware/labour cost assumptions filled', local_cost_ready(cfg)))

    api_ok = all(api_key_for(m) for m in cfg['models'] if m['provider'] != 'ollama')
    checks.append(row('API key available privately', api_ok, '.env is the recommended location'))

    local_model = next(m for m in cfg['models'] if m['provider'] == 'ollama')
    try:
        tags = request_json('http://localhost:11434/api/tags', timeout=5)
        local_ok = any(x.get('name') == local_model['model'] for x in tags.get('models', []))
    except (urllib.error.URLError, TimeoutError, OSError):
        local_ok = False
    checks.append(row('Ollama local model available', local_ok, local_model['model']))

    result_ok, result_detail = final_results_ready(cfg)
    checks.append(row('Final three-model results published', result_ok, result_detail))

    report = ROOT / 'report.pdf'
    checks.append(row('Two-page report file exists', report.exists() and report.stat().st_size > 1000))

    post = (ROOT / 'postmortem.md').read_text(encoding='utf-8') if (ROOT / 'postmortem.md').exists() else ''
    post_ok = bool(post) and 'real benchmark not run yet' not in post.lower() and 'complete after' not in post.lower()
    checks.append(row('Postmortem based on measured results', post_ok))

    gitignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
    checks.append(row('.env is ignored by Git', '.env' in gitignore))

    if all(checks):
        print('\nREADY FOR SUBMISSION: all automated checks pass. Still open report.pdf and inspect it manually.')
        return

    print('\nNot finished yet. This is expected before the teacher gives the API key/final run.')
    raise SystemExit(1)


if __name__ == '__main__':
    main()
