"""Local results dashboard. Start: python -m src.dashboard (no extra packages).

Serves only the dashboard and selected experiment data, never the project tree.
Reuses the existing prompt, request adapter, scorer and metric calculations.
"""
import argparse
import csv
import io
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from src import run
from src.cost import percentile, local_scenario

ROOT = Path(__file__).resolve().parents[1]
TOKEN = secrets.token_urlsafe(32)
JOB_LOCK = threading.Lock()
JOB = {'running': False, 'mode': None, 'exit_code': None, 'log': []}


def read_rows(path):
    if not path.exists():
        return []
    # The benchmark flushes each row. Ignore a row still being written.
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r.get('status') and r.get('correct') in ('0', '1')
            and r.get('latency_ms') and r.get('item_id') and r.get('error') is not None]


def runs():
    folder = ROOT / 'results/runs'
    found = []
    if folder.exists():
        for path in sorted(folder.iterdir(), reverse=True):
            if path.is_dir() and (path / 'metadata.json').exists():
                try:
                    meta = run.read_json(path / 'metadata.json')
                    found.append({'id': path.name, 'split': meta.get('split', 'unknown'),
                                  'complete': bool(meta.get('complete')),
                                  'scope': meta.get('scope', 'three_models'),
                                  'started': meta.get('started_utc', path.name)})
                except (ValueError, OSError):
                    continue  # Retry on the next poll while metadata is being written.
    return found


def selected_path(identifier):
    if identifier not in {r['id'] for r in runs()}:
        raise ValueError('Select an existing experiment.')
    return ROOT / 'results/runs' / identifier


def metrics(rows, cfg, target_count):
    result = []
    for model in cfg['models']:
        batch = [r for r in rows if r['role'] == model['role']]
        count = len(batch)
        times = [float(r['latency_ms']) for r in batch]
        correct = sum(int(r['correct']) for r in batch)
        cost = None
        cost_note = 'No measurements yet'
        tps = None
        if count and model['provider'] == 'gemini':
            if all(r.get('api_cost_usd') not in ('', None) for r in batch):
                cost = 1000 * sum(float(r['api_cost_usd']) for r in batch) / count
                cost_note = 'Standard list price, including reported thinking tokens'
            else:
                cost_note = 'Unknown: missing usage for one or more requests'
        elif count:
            scenario = local_scenario(sum(times) / count / 1000, cfg['local_cost'])
            cost = scenario.get('cost_per_1k_usd')
            cost_note = scenario['status']
            durations = sum(float(r.get('eval_duration_ns') or 0) for r in batch) / 1e9
            tps = sum(int(r.get('eval_count') or 0) for r in batch) / durations if durations else None
        result.append({'role': model['role'], 'model': model['model'], 'count': count,
                       'target': target_count, 'correct': correct, 'incorrect': count-correct,
                       'accuracy': correct/count if count else None,
                       'p50': percentile(times, .5) if times else None,
                       'p95': percentile(times, .95) if times else None,
                       'cost': cost, 'cost_note': cost_note, 'tokens_per_second': tps,
                       'failures': {status: sum(r['status'] == status for r in batch)
                                    for status in sorted({r['status'] for r in batch if r['status'] != 'correct'})}})
    return result


def dashboard_data(identifier=''):
    catalogue = runs()
    cfg = run.read_json(ROOT / 'config.json')
    meta = {}; rows = []; items = []; selected = ''
    if identifier or catalogue:
        selected = identifier or catalogue[0]['id']
        path = selected_path(selected)
        meta = run.read_json(path / 'metadata.json')
        cfg = meta['settings']  # Never recalculate old runs using new model prices.
        rows = read_rows(path / 'per_item.csv')
        if (path / 'items.json').exists(): items = run.read_json(path / 'items.json')
    count = len(meta.get('item_ids', [])) or len(run.load_data('test')[0])
    summaries = metrics(rows, cfg, count)
    # Rank only complete, comparable three-model test runs on identical item IDs.
    comparable = bool(meta.get('complete')) and meta.get('split') == 'test' and count >= 50
    comparable = comparable and {m['role'] for m in cfg['models']} == {'top_api', 'cheap_api', 'local'}
    for model in cfg['models']:
        comparable = comparable and [r['item_id'] for r in rows if r['role'] == model['role']] == meta.get('item_ids')
    winners = []
    if comparable:
        best = max(s['correct'] for s in summaries)
        winners = [s['role'] for s in summaries if s['correct'] == best]
    test_items, _ = run.load_data('test')
    try: reviewed = bool(run.reviews_ready(test_items))
    except (OSError, ValueError, KeyError): reviewed = False
    with JOB_LOCK: job = {**JOB, 'log': JOB['log'][-30:]}
    return {'runs': catalogue, 'selected': selected, 'split': meta.get('split'),
            'complete': bool(meta.get('complete')), 'scope': meta.get('scope', 'three_models'),
            'comparable': bool(comparable), 'winners': winners, 'models': summaries, 'rows': rows,
            'items': items, 'expected_total': count*len(cfg['models']), 'job': job,
            'api_key_ready': all(run.api_key_for(m) for m in cfg['models'] if m['provider'] != 'ollama'), 'reviews_ready': reviewed,
            'cost_ready': run.local_cost_ready(cfg), 'csrf': TOKEN}


def local_practice():
    """Ten dev items; no API key and no alteration to the final test results."""
    cfg = run.read_json(ROOT / 'config.json')
    if cfg['temperature'] != 0: raise ValueError('Temperature must be 0.')
    model = next(m for m in cfg['models'] if m['provider'] == 'ollama')
    tags = run.request_json('http://localhost:11434/api/tags', timeout=10)
    found = next((m for m in tags.get('models', []) if m.get('name') == model['model']), None)
    if not found: raise ValueError('Download the model first: ollama pull '+model['model'])
    items, vocab = run.load_data('dev')
    cfg = {**cfg, 'models': [model]}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = ROOT / 'results/runs' / ('dev-local-'+stamp)
    path.mkdir(parents=True)
    meta = {'started_utc': stamp, 'split': 'dev', 'scope': 'local_practice', 'settings': cfg,
            'complete': False, 'item_ids': [i['id'] for i in items], 'sha256': run.fingerprint(),
            'hardware': {'model': found, 'os': platform.platform(), 'cpu': platform.processor()},
            'latency_policy': 'Full request wall time; includes first cold load, excludes pacing.', 'retries': 0}
    (path / 'metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    (path / 'items.json').write_text(json.dumps(items, indent=2), encoding='utf-8')
    (path / 'prompts.json').write_text(json.dumps([run.prompt_for(i, vocab) for i in items]), encoding='utf-8')
    with (path / 'per_item.csv').open('w', encoding='utf-8', newline='') as f, (path / 'raw.jsonl').open('w', encoding='utf-8') as rawfile:
        writer = csv.DictWriter(f, fieldnames=run.FIELDS); writer.writeheader(); f.flush()
        for item in items:
            row = {key: '' for key in run.FIELDS}
            row.update(role=model['role'], model=model['model'], item_id=item['id'],
                       abbreviation=item['abbreviation'], expected=item['expected'], correct=0,
                       timestamp_utc=datetime.now(timezone.utc).isoformat())
            raw = None; start = time.perf_counter()
            try:
                raw = run.call_model(model, run.prompt_for(item, vocab), cfg)
                row['latency_ms'] = (time.perf_counter()-start)*1000
                output, forced, usage = run.decode_response(raw, model)
                correct, status, parsed = run.score(output, item['expected'], vocab)
                row.update(output=output, parsed=parsed, correct=0 if forced else correct, status=forced or status, **usage)
            except urllib.error.HTTPError as exc:
                row.update(status='api_error', error='HTTP '+str(exc.code))
            except (TimeoutError, socket.timeout):
                row.update(status='timeout', error='Request deadline exceeded')
            except urllib.error.URLError as exc:
                row.update(status='timeout' if isinstance(exc.reason, (TimeoutError, socket.timeout)) else 'connection_error', error=type(exc.reason).__name__)
            except (ValueError, TypeError, KeyError) as exc:
                row.update(status='response_error', error=type(exc).__name__)
            if row['latency_ms'] == '': row['latency_ms'] = (time.perf_counter()-start)*1000
            writer.writerow(row); f.flush()
            rawfile.write(json.dumps({'role': model['role'], 'item_id': item['id'], 'response': raw, 'error': row['error']})+'\n'); rawfile.flush()
            print(item['id'], row['status'], flush=True)
            time.sleep(cfg['pause_seconds'])
    meta['complete'] = True
    (path / 'metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    print('Local practice complete. Final benchmark files were not changed.', flush=True)


def start_job(mode):
    if mode not in ('local', 'test'): raise ValueError('Unknown run type.')
    if mode == 'test':
        if not all(run.api_key_for(m) for m in run.read_json(ROOT/'config.json')['models'] if m['provider'] != 'ollama'): raise ValueError('Put the teacher API key in .env as described in START_HERE.md, then restart the dashboard.')
        if not run.reviews_ready(run.load_data('test')[0]): raise ValueError('Complete both human label reviews before running the final test.')
        if not run.local_cost_ready(run.read_json(ROOT/'config.json')): raise ValueError('Fill the three local_cost assumptions in config.json before the final test; see START_HERE.md.')
    with JOB_LOCK:
        if JOB['running']: raise ValueError('A run is already in progress. Wait for it to finish.')
        JOB.update(running=True, mode=mode, exit_code=None, log=[])
    def worker():
        command = [sys.executable, '-u', '-m', 'src.dashboard', '--local-practice'] if mode == 'local' else [sys.executable, '-u', '-m', 'src.run']
        try:
            with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding='utf-8', errors='replace') as process:
                for line in process.stdout:
                    # Prevent accidentally exposing a key if an underlying error ever includes it.
                    keys = [run.api_key_for(m) for m in run.read_json(ROOT/'config.json')['models'] if m['provider'] != 'ollama']
                    for key in filter(None, keys):
                        line = line.replace(key, '[redacted]')
                    with JOB_LOCK: JOB['log'] = (JOB['log']+[line.rstrip()])[-30:]
                code = process.wait()
        except OSError as exc:
            code = 1
            with JOB_LOCK: JOB['log'].append(type(exc).__name__+': could not start the Python process.')
        with JOB_LOCK: JOB.update(running=False, exit_code=code)
    threading.Thread(target=worker, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def reply(self, body, kind='application/json; charset=utf-8', status=200):
        if not isinstance(body, bytes): body = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers(); self.wfile.write(body)

    def valid_host(self):
        port = self.server.server_port
        return self.headers.get('Host') in (f'localhost:{port}', f'127.0.0.1:{port}')

    def do_GET(self):
        if not self.valid_host(): return self.reply({'error': 'Local access only.'}, status=403)
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == '/':
                return self.reply((ROOT / 'src/dashboard.html').read_bytes(), 'text/html; charset=utf-8')
            if parsed.path == '/api/data':
                return self.reply(dashboard_data(query.get('run', [''])[0]))
            if parsed.path == '/api/csv':
                path = selected_path(query.get('run', [''])[0])
                # Raw download preserves the evidence; only this known file is exposed.
                return self.reply((path / 'per_item.csv').read_bytes(), 'text/csv; charset=utf-8')
            return self.reply({'error': 'Not found'}, status=404)
        except (ValueError, OSError, KeyError) as exc:
            return self.reply({'error': str(exc)}, status=400)

    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Dashboard-Token') != TOKEN:
            return self.reply({'error': 'Refresh the dashboard before starting a run.'}, status=403)
        if self.path != '/api/start': return self.reply({'error': 'Not found'}, status=404)
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size < 1024: raise ValueError('Invalid request.')
            body = json.loads(self.rfile.read(size))
            start_job(body['mode'])
            return self.reply({'ok': True})
        except (ValueError, KeyError) as exc:
            return self.reply({'error': str(exc)}, status=400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8501)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--local-practice', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.local_practice:
        try: local_practice()
        except (ValueError, urllib.error.URLError) as exc: raise SystemExit(str(exc))
        return
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = f'http://127.0.0.1:{server.server_port}'
    print('Dashboard: '+url, flush=True)
    print('Keep this terminal open. Ctrl+C stops the dashboard. Let active runs finish first.', flush=True)
    if not args.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nDashboard stopped.')
    finally: server.server_close()


if __name__ == '__main__': main()
