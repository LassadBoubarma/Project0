"""Verify API credentials and configured Gemini model access without running the benchmark."""
import os
import urllib.error
import urllib.parse

from src.run import ROOT, api_key_for, read_json, request_json


def main():
    cfg = read_json(ROOT / 'config.json')
    api_models = [m for m in cfg['models'] if m['provider'] != 'ollama']
    if not api_models:
        raise SystemExit('No API models configured.')

    failures = 0
    for model in api_models:
        key = api_key_for(model)
        env_name = model.get('api_key_env', 'GEMINI_API_KEY')
        if not key:
            print(f"MISSING  {model['model']} - set {env_name} in .env")
            failures += 1
            continue
        if model['provider'] != 'gemini':
            print(f"UNSUPPORTED CHECK  {model['model']} - provider {model['provider']}")
            failures += 1
            continue
        url = ('https://generativelanguage.googleapis.com/v1beta/models/' +
               urllib.parse.quote(model['model'], safe=''))
        try:
            raw = request_json(url, headers={'x-goog-api-key': key}, timeout=30)
            print(f"OK       {model['model']} - API access verified ({raw.get('name', 'model found')})")
        except urllib.error.HTTPError as exc:
            print(f"FAILED   {model['model']} - HTTP {exc.code}")
            failures += 1
        except urllib.error.URLError as exc:
            print(f"FAILED   {model['model']} - connection error: {type(exc.reason).__name__}")
            failures += 1

    if failures:
        raise SystemExit(f'{failures} API check(s) failed. See START_HERE.md.')
    print('API check complete. No benchmark requests were made.')


if __name__ == '__main__':
    main()
