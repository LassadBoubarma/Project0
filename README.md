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

If setup says that the `ollama` command is unavailable, install Ollama and
restart PowerShell so its command is added to `PATH`. If it says the local
service is not running, launch the Ollama application first. You can verify
both from PowerShell:

```powershell
ollama --version
Invoke-WebRequest http://localhost:11434/api/tags
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

Run: `20260914T001358897252Z`

| Model        | Correct | Accuracy | p50 ms | p95 ms | USD / 1k | Tokens/s | Parse | Refusal | Timeout | Other |
| ------------ | ------: | -------: | -----: | -----: | -------: | -------: | ----: | ------: | ------: | ----: |
| qwen2.5:1.5b |   16/50 |    32.0% |   2228 |   2413 |   5.0950 |     50.6 |    33 |       0 |       0 |     0 |
| qwen2.5:3b   |   16/50 |    32.0% |   2223 |   2361 |   5.0956 |     58.7 |    33 |       0 |       0 |     0 |
| qwen2.5:7b   |   27/50 |    54.0% |   2272 |   2387 |   5.0989 |     37.0 |    22 |       0 |       0 |     0 |

No model meets the project's 95% accuracy + p95<10s target. For this benchmark, choose the highest-accuracy model: qwen2.5:7b at 27/50 (54.0%).

<!-- RESULTS_END -->

**p50** is the middle response time; **p95** is the time within which 95% of
requests finished. **Parse** includes answers outside the fixed vocabulary.

Local models have no paid API fee. The cost estimates include hardware and
operator time, using assumptions in `config.json`. This is a wording benchmark,
not evidence that a model is suitable for clinical use.

## Where to find things

| File or folder                 | What it contains                                                           |
| ------------------------------ | -------------------------------------------------------------------------- |
| [report.pdf](report.pdf)       | Two-page report: results, mistakes, model choice and costs at 100x traffic |
| [postmortem.md](postmortem.md) | Problems we encountered and what we learned                                |
| [data/](data/)                 | Questions, correct answers and label-review records                        |
| [src/](src/)                   | Prompt, runner, scorer, cost calculation and dashboard                     |
| [results/](results/)           | Saved answers, measurements and hardware details                           |

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
