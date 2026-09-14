# Medical abbreviation bake-off

Compare three local LLMs on the same 50 medical-abbreviation questions. Each model
gets one prompt per question. Python checks the answer and measures accuracy,
latency, generation speed and estimated cost. No paid API or API key is needed.

**Models:** `qwen2.5:1.5b`, `qwen2.5:3b`, `qwen2.5:7b`, served locally by Ollama.

## Start here

First install Python 3.10+ and [Ollama](https://ollama.com/download), and start
Ollama. Open a terminal in this project folder.

**One setup command** (creates `.venv`, installs the two Python dependencies and
downloads the three models; allow several GB of disk space):

```powershell
python -m src.run --setup
```

**One run command** (opens the dashboard in your browser):

```powershell
.venv\Scripts\python.exe -m src.dashboard
```

Use **Practice** for the small model's 10 development questions. Use **Run test**
for all three models on the 50 test questions: 150 sequential calls. The dashboard
shows saved results immediately, even when Ollama is stopped. Keep the terminal
open while using it. On macOS/Linux, replace `.venv\Scripts\python.exe` with
`.venv/bin/python` in the commands below.

| Optional action | Command after setup |
|---|---|
| Run the final benchmark without the dashboard | `.venv\Scripts\python.exe -m src.run` |
| Practice without the dashboard | `.venv\Scripts\python.exe -m src.run --practice` |
| Check data and saved evidence, without inference | `.venv\Scripts\python.exe -m src.run --check` |
| Rebuild the report from saved responses | `.venv\Scripts\python.exe -m src.report` |
| Run automated tests, without inference | `.venv\Scripts\python.exe -m unittest discover -s tests` |

If a model is missing, rerun setup. If Ollama is unavailable, open the Ollama
application or run `ollama serve`. If port 8501 is occupied, start the dashboard
with `--port 8502`. A failed benchmark stays in its own run folder; the last
complete test remains published. Runs are never automatically retried.

## Understand the project in five minutes

Read these files in order. The three core files named in the assignment stay
separate so each has one clear job.

| File | What it does |
|---|---|
| `config.json` | Three model names, shared settings and local cost assumptions |
| `data/items.jsonl` | 50 test questions and their correct answers |
| `data/dev.jsonl` | 10 separate practice questions |
| `src/prompt.txt` | The same instruction for every model; only context and abbreviation are inserted |
| `src/score.py` | Compares one answer with the canonical label |
| `src/run.py` | Setup, checks, and one shared loop for practice and final runs |
| `src/cost.py` | Percentiles and the local cost calculation |
| `src/report.py` | Validates saved evidence and creates tables and the two-page PDF |
| `src/dashboard.py` | Small local server; starts the shared runner and serves results |
| `src/dashboard.html` | The browser interface; search, filters and CSV download |

The flow is `question -> prompt -> Ollama -> raw answer -> scorer -> CSV -> report`.
The expected answer and `data/word_list.json` are used only by the scorer.

## Fair comparison

- Same frozen items, order, prompt, parser and temperature 0 for every model.
- Output limit 64 tokens; context window 8192; one sequential request per item.
- No retrieval, chat history, agents, retries or manual answer repair.
- Trim outer whitespace and ignore letter case; otherwise require exact wording.
  Synonyms, punctuation, explanations and singular/plural changes are rejected.
- Every attempt stays in the denominator, including timeout and parse errors.
  Explicit refusals starting with the fixed phrases in `score.py` are counted
  in the refusal column. Other unrecognised text is a parse error; this simple
  detector does not recognise every possible refusal wording.
- Latency is full request wall time. Any model loading during the request is
  included; the one-second pause between calls is excluded. A first call is not
  guaranteed cold if a model is already loaded. Tokens/s uses Ollama's generation
  token count divided by generation duration, not total request time.
- p50 and p95 use linear interpolation over all attempts, including failures.

Data provenance, the non-random dev/test split and the review protocol are in
`data/labelling_note.md`. This measures canonical wording, not clinical competence.
The local request and usage fields follow the [Ollama chat API](https://docs.ollama.com/api/chat).

## Saved results

At delivery, the included measurements were imported from your original ZIP's completed run
`test-local3-20260913T183731049814Z` (13 September 2026). They are **not a new
benchmark of the simplified code**. Raw responses, times and original metadata
are preserved. The original source hashes still describe the original code;
the refactored source naturally has different hashes. The data, prompt,
configuration and correct/incorrect rules are unchanged. A fixed refusal-prefix
detector now separates obvious refusals from parse errors; it changes none of
the 150 saved classifications.

<!-- RESULTS_START -->

Run: `20260914T001358897252Z`

| Model | Correct | Accuracy | p50 ms | p95 ms | USD / 1k | Tokens/s | Parse | Refusal | Timeout | Other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| qwen2.5:1.5b | 16/50 | 32.0% | 2228 | 2413 | 5.0950 | 50.6 | 33 | 0 | 0 | 0 |
| qwen2.5:3b | 16/50 | 32.0% | 2223 | 2361 | 5.0956 | 58.7 | 33 | 0 | 0 | 0 |
| qwen2.5:7b | 27/50 | 54.0% | 2272 | 2387 | 5.0989 | 37.0 | 22 | 0 | 0 | 0 |

No model meets the project's 95% accuracy + p95<10s target. For this benchmark, choose the highest-accuracy model: qwen2.5:7b at 27/50 (54.0%).

<!-- RESULTS_END -->

The table and decision above update when you publish a new complete test. Prefer
a smaller model if it reaches the required accuracy at lower latency/cost on a
separately frozen follow-up set. A larger model is not automatically good enough.

The PDF includes three wrong answers per model and the cost scenarios. Inspect
all 150 responses in `results/per_item.csv` or the dashboard. `results/summary.csv`
is derived from that evidence; `results/hardware.md` records the machine and
model digests. `results/latest_run.txt` points to the last published test.
New runs get separate timestamped folders in `results/runs/` and snapshots of
their items, prompts, settings and raw responses. Do not edit saved evidence.
Regenerating the report does **not** overwrite the human-written postmortem.

## What “free” means and how cost is calculated

There are no paid API requests. Hardware, electricity and operator time are
still estimated for the assignment. The supplied assumptions are $0.15 per active
hardware hour and one operator hour/month at $5/hour. They are assumptions, not
measured invoices. Baseline traffic is 1,000 requests/month; 100x is 100,000.

For mean request time `s`, hardware rate `H`, monthly labour `F` and volume `N`:

```text
requests per hour = 3600 / s
variable cost per request v = H / requests per hour
monthly cost = F + N * v
cost per 1,000 requests = 1000 * (v + F / N)
monthly capacity = requests per hour * available hours per month
```

These scenarios charge active processing time, exclude the benchmark's pacing
pause, and assume unchanged throughput and labour at higher traffic. They model
each candidate as an alternative deployment, not all three serving together.
The PDF checks whether 100x traffic fits the configured 160 hours/month.
Always-on rental or additional machines would require a different cost model.

For an API cost `A` per request, the theoretical break-even volume is
`N = F / (A - v)` when `A > v` and capacity permits. No API was measured here,
so there is no measured numerical API/local break-even result.

## Assignment checklist and the local-only change

| PDF requirement | This project |
|---|---|
| Small task with an automatic correct answer | Medical abbreviation expansion, fixed vocabulary and exact scorer |
| At least 50 test items and separate development data | 50 test + 10 dev; two reviewer names recorded for every label |
| Three models under the same conditions | Three local Qwen sizes with identical settings |
| Top API + cheap API + locally run open model | **Changed at your request to three local models; instructor acceptance is not documented** |
| Accuracy n/50, error columns, p50/p95, tokens/s and hardware | CSVs, dashboard and two-page report |
| Cost today, at 100x, and API/local break-even | Local scenarios and capacity; formula only for API break-even because no API was measured |
| README, source, data, report and postmortem | Included; only the human team can confirm its contributions and review records |
| Explain every line and demonstrate it | Read the source in the order above; practice uses dev data |

This is a runnable **local-only adaptation**, not a claim that the original
API/API/local requirement is satisfied. The PDF also asks for task approval by
Day 2, a team of at most four, a repository freeze before Week 2 and a demo in
the first Week 2 session. Those course actions cannot be verified from the ZIP.

## Contributions

The supplied review CSV records the following contributions. Confirm the actual
team roster and add each member's implementation/report work before submission;
the ZIP does not establish who wrote which code.

| Recorded name | Documented contribution |
|---|---|
| Lassaad | Listed as reviewer 1 for all 60 labels on 2026-09-11 |
| Rami | Listed as reviewer 2 for all 60 labels on 2026-09-11 |

AI assistance was used to draft the original synthetic contexts and to simplify
this project. Review entries are preserved as supplied, not independently
verified human approvals.

## What was simplified

Removed bundled `.venv`, Git internals, bytecode, old development runs and the
superseded final run from this delivery. Your original ZIP retains those files.
Merged the setup/readiness commands into `run.py`, removed the dashboard's
duplicate benchmark loop, and consolidated repeated instructions into this README.
Removed separate generated decision, error-analysis, cost-scenario and table
files: that information belongs in the report, README and CSVs. The latest run's
raw evidence stays because it makes the experiment checkable.

## Verification of this simplified version

A clean copy was set up with Python 3.14 and the pinned dependencies. All 17
automated tests passed, including saved-output replay, invalid configuration,
corrupted evidence, timeouts, malformed responses, truncation and practice
isolation. A real development run made 10 calls to each installed Qwen model
(30 total); all completed and all 30 dev answers matched. This is a smoke test,
not a replacement for the 50-item final benchmark. Dashboard rendering, search
and model filtering were checked. The two-page PDF was rendered and inspected.
The original final CSV metrics are unchanged.
