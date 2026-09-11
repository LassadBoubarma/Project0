# Medical Abbreviation Bake-Off

CS496 AI Engineering - Project 0

## Task

Compare three language models on **medical abbreviation expansion**. Each item contains one abbreviation in a short UK medical-record context and one fixed canonical answer. The scorer is deterministic: no human or LLM judge is used during evaluation.

Example: `What does BP mean here?` -> `blood pressure`

Dataset: **50 frozen test items + 10 separate development items**. The mappings are sourced from the NHS abbreviation glossary; the contexts are synthetic and contain no patient data.

## Models

| Role | Model | How it runs |
|---|---|---|
| Top API | `gemini-3.1-pro-preview` | Gemini API |
| Cheap API | `gemini-3.5-flash-lite` | Gemini API |
| Local open weights | `qwen2.5:1.5b` | Ollama on our own hardware |

All three receive the same literal prompt, same ordered items, temperature `0`, output-token limit `64`, and the same parser/scorer. Calls are sequential and are not retried or repaired.

## One setup command

```powershell
python setup.py
```

This creates `.venv`, installs dependencies, and runs an offline validation. Ollama itself must also be installed and the local model downloaded once:

```powershell
ollama pull qwen2.5:1.5b
```

## One final run command

After the two-person label review, local cost assumptions, Ollama setup and API key are ready:

```powershell
.\.venv\Scripts\python.exe -m src.run
```

The same final run can also be started from the dashboard:

```powershell
.\.venv\Scripts\python.exe -m src.dashboard
```

Then open `http://127.0.0.1:8501` and click **Run 3-model test**.

Read **[START_HERE.md](START_HERE.md)** before the final run. It explains exactly where the API key goes and what must be completed first.

## Evaluation

The project reports:

- exact-match accuracy as `n / 50` and percentage;
- parse errors, refusals, timeouts and other failures (all count as wrong);
- p50 and p95 full-response latency in milliseconds;
- API cost per 1,000 requests from the real usage fields and list prices;
- local generation tokens/second and hardware details;
- local cost today, cost at 100x traffic, and API/local break-even volume.

Every real response is preserved in an archived run under `results/runs/`. The final published CSVs are built from those real runs.

<!-- RESULTS_START -->

| Model | Correct | Accuracy | p50 ms | p95 ms | USD / 1k | Parse | Refusal | Timeout | Other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Real benchmark not yet run | pending | pending | pending | pending | pending | pending | pending | pending | pending |

<!-- RESULTS_END -->

## Files

- `data/items.jsonl` - 50 frozen test questions and gold answers.
- `data/dev.jsonl` - 10 development/practice questions, no overlap with test abbreviations.
- `data/word_list.json` - fixed output vocabulary.
- `data/label_reviews.csv` - two-person human label check (must be completed honestly).
- `data/labelling_note.md` - source, split and label policy.
- `src/prompt.txt` - the one prompt used for every model.
- `src/run.py` - sequential benchmark runner.
- `src/score.py` - deterministic exact scorer.
- `src/cost.py` - API and self-hosted cost calculations.
- `src/report.py` - creates results tables, error analysis, decision, postmortem and the 2-page report.
- `src/dashboard.py` / `src/dashboard.html` - local results dashboard.
- `src/api_check.py` - verifies the teacher's API key/model access without running the benchmark.
- `src/final_check.py` - shows what is still missing before submission.
- `results/per_item.csv` / `results/summary.csv` - final published results after the test run.
- `results/hardware.md` - local hardware/model/cost note.
- `report.pdf` - 2-page report, regenerated after the final run.
- `postmortem.md` - generated from real observed results/problems after the final run.

## Reproducibility rules

Do not change the test set, prompt, scorer or settings after looking at final test outcomes. Do not delete failed rows. Do not manually repair model output. A refusal, malformed response or timeout is wrong. The runner stores file hashes, exact prompts, raw API responses, model versions and timestamps for each run.

## Secrets

`.env`, `.env.*` and the virtual environment are ignored by Git. **Never put an API key in `config.json`, Python files, screenshots, CSVs or GitHub.**

## Contributions

- Lassad Boubarma: task selection, implementation, local testing, experiment execution and analysis (update after the final run to match actual work).
- Add each additional team member and their real contribution.
- AI assistance: code/documentation drafting and synthetic context drafting; human reviewers remain responsible for the required label verification.
