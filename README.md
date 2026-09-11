# Medical Abbreviation Bake-Off

CS496 — Project 0

## Task

Compare three language models on medical abbreviation expansion using 50 test questions and 10 separate development questions.

Each question has one fixed expected answer. Responses are scored automatically using exact matching against a fixed vocabulary.

Example: “What does BP mean?” → `blood pressure`

## Models

* Top API candidate: Gemini 3.1 Pro Preview
* Cheap API: Gemini 3.5 Flash-Lite
* Local open-weights model: Qwen2.5 1.5B through Ollama

Model identifiers and prices are configured in `config.json`. Confirm their availability and suitability before the final experiment.

All models receive the same prompts, questions, vocabulary, temperature of 0 and output-token limit.

## Setup and execution

Requires Python 3.10+, a Gemini API key stored in `GEMINI_API_KEY`, and Ollama running locally with `qwen2.5:1.5b` installed.

Setup on Windows:

```powershell
py setup.py
```

Run after completing the label reviews and hardware cost assumptions:

```powershell
.\.venv\Scripts\python.exe -m src.run
```

## Evaluation

Report accuracy, p50/p95 latency, cost per 1,000 requests and failure counts. Incorrect answers, parsing errors, refusals and timeouts count as wrong.

Real benchmark results are pending.

<!-- RESULTS_START -->

Results will be generated after the experiment.

<!-- RESULTS_END -->

## Files

* `data/`: test questions, development questions, vocabulary and label reviews.
* `src/`: prompts, model requests, scoring, cost calculations and reporting.
* `results/`: per-item results, summary and hardware information.
* `report.pdf`: two-page report; currently a draft.
* `postmortem.md`: limitations and lessons; complete after the experiment.

## Contributions

* Lassad Boubarma: task selection. Record further contributions after completing them.
* Add each additional team member and their actual contribution.
* AI assistance: initial code, synthetic contexts and documentation drafting.

Two-person label review, real model runs and final analysis remain to be completed.
