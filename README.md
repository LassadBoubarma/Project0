# Medical abbreviation bake-off

**CS496 AI Engineering - Project 0**

We compare three local models: **Qwen 2.5 1.5B, 3B and 7B**. Each model answers
the same 50 medical-abbreviation questions. We measure correct answers, response
time and estimated cost.

Example: **BP** should become **blood pressure** in the matching context.

## Start here

Install Python 3.10+ and [Ollama](https://ollama.com/download). Start Ollama and
open a terminal in this project folder.

**1. Set up once:**

```powershell
python -m src.run --setup
```

**2. Open the dashboard:**

```powershell
.venv\Scripts\python.exe -m src.dashboard
```

**3. Try it:** click **small-model practice** for 10 questions, then
**Run 3-model test** for the full 150 requests.

If the browser does not open, visit [localhost:8501](http://127.0.0.1:8501).
Keep the terminal open. Press **Ctrl+C** to stop.

## How the comparison works

- **50 test questions + 10 separate practice questions.** Labels follow the
  [NHS glossary](https://www.nhs.uk/nhs-app/help/understanding-abbreviations/);
  contexts are synthetic, with no real patient data.
- All models receive the **same questions, prompt and settings**: temperature 0,
  64 output tokens, one request at a time, with no retries.
- Correct answers are hidden from the models. Python checks the exact wording,
  ignoring capitalization and whitespace around the answer.
- Different wording, extra explanations and failed requests count as wrong.
  We reviewed mistakes without changing the final scores.

## Results

<!-- RESULTS_START -->

Run: `20260914T142257327036Z`

| Model | Correct | Accuracy | p50 ms | p95 ms | USD / 1k | Tokens/s | Parse | Refusal | Timeout | Other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| qwen2.5:1.5b | 15/50 | 30.0% | 2654 | 3051 | 5.1127 | 12.7 | 35 | 0 | 0 | 0 |
| qwen2.5:3b | 24/50 | 48.0% | 3280 | 3885 | 5.1429 | 6.6 | 25 | 0 | 0 | 0 |
| qwen2.5:7b | 29/50 | 58.0% | 4324 | 5092 | 5.1933 | 4.2 | 17 | 0 | 0 | 0 |

No model meets the project's 95% accuracy + p95<10s target. For this benchmark, choose the highest-accuracy model: qwen2.5:7b at 29/50 (58.0%).

<!-- RESULTS_END -->

**p50** is the middle response time; **p95** is the time within which 95% of
requests finished. **Parse** includes answers outside the fixed vocabulary.

Local models have no paid API fee. The cost estimates include hardware and
operator time, using assumptions in `config.json`. This is a wording benchmark,
not evidence that a model is suitable for clinical use.

## Where to find things

| File or folder | What it contains |
|---|---|
| [report.pdf](report.pdf) | Two-page report: results, mistakes, model choice and costs at 100x traffic |
| [postmortem.md](postmortem.md) | Problems we encountered and what we learned |
| [data/](data/) | Questions, correct answers and label-review records |
| [src/](src/) | Prompt, runner, scorer, cost calculation and dashboard |
| [results/](results/) | Saved answers, measurements and hardware details |

## Useful commands

Check the data and saved results without calling a model:

```powershell
.venv\Scripts\python.exe -m src.run --check
```

Rebuild the report from saved results:

```powershell
.venv\Scripts\python.exe -m src.report
```

Run the automated tests:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
```

## Contributions

- **Rami:** UI, part of the code, prepared half the labels and reviewed all 60.
- **Lassaad:** part of the code, prepared half the labels, reviewed all 60,
  report and postmortem.

AI assistance was used for drafting, refactoring and analysis. Both members
are responsible for reviewing and understanding the project.

## Before submission

The assignment asks for **two API models and one local model**. Our version uses
**three local models** to avoid paid APIs.

The team confirms that **Lassaad and Rami each checked every label**.
