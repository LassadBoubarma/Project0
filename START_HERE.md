# START HERE - finish and run Project 0

This repository is deliberately **ready but not allowed to invent missing evidence**. The only things that must come from you/your team are: two real human label reviews, your actual local cost assumptions, your real hardware, and the API key/access supplied by the teacher.

## A. Do this now (no API key needed)

### 1. Setup from the project root

```powershell
python setup.py
```

### 2. Install Ollama and download the local model

Install Ollama, then:

```powershell
ollama pull qwen2.5:1.5b
ollama list
```

### 3. Local practice only

```powershell
.\.venv\Scripts\python.exe -m src.dashboard
```

Click **Run local practice - 10 questions**. This is only the development split and is not the final comparison.

### 4. Complete the required two-person label review

Open `data/label_reviews.csv`. Two different real people must independently check every abbreviation/answer against the source described in `data/labelling_note.md`.

For each row fill:

- `reviewer_1`
- `reviewer_2`
- `checked_date` (use `YYYY-MM-DD`)
- optional `notes`

Do not put fake reviewer names. If a label is genuinely wrong or ambiguous, fix/replace it **before** the final test and document the reason. Once the final test is run, freeze the data.

### 5. Fill the local cost assumptions

Open `config.json` and replace the three `null` values under `local_cost`:

```json
"hardware_usd_per_hour": null,
"labour_hours_per_month": null,
"labour_usd_per_hour": null
```

Use your real assumptions. For an owned PC, a reasonable method is:

`hardware USD/hour = computer depreciation per operating hour + electricity cost per hour`

The assignment asks for hardware cost plus your time, so do not invent a rental price. Keep the calculation/source in `results/hardware.md` if you want to explain the assumption.

## B. WHEN THE TEACHER GIVES YOU THE API KEY

Do **not** put the key in Python or `config.json`.

### 1. Create your private `.env`

In PowerShell from the project root:

```powershell
Copy-Item .env.example .env
```

Open `.env` and change:

```text
GEMINI_API_KEY=PASTE_THE_TEACHER_KEY_HERE
```

to the real key. Save the file. `.env` is already ignored by Git.

### 2. Verify the key and the two configured API models

```powershell
.\.venv\Scripts\python.exe -m src.api_check
```

Expected result: both configured Gemini models show `OK`.

If the teacher gives a key for a **different provider or different model names**, do not guess. Update `config.json`/the adapter first; the current code is prepared for the two Gemini models shown in the README.

### 3. Check that everything is ready

```powershell
.\.venv\Scripts\python.exe -m src.final_check
```

Before the final benchmark, the remaining pre-run checks should all say `OK`.

## C. RUN THE FINAL EXPERIMENT ONCE THE SETUP IS FROZEN

CLI:

```powershell
.\.venv\Scripts\python.exe -m src.run
```

or dashboard:

```powershell
.\.venv\Scripts\python.exe -m src.dashboard
```

then click **Run 3-model test**.

The final run performs 50 sequential calls per model (150 model calls total), keeps failures in the denominator, archives raw responses and automatically regenerates:

- `results/per_item.csv`
- `results/summary.csv`
- `results/hardware.md`
- `results_table.md`
- `error_analysis.md`
- `decision.txt`
- `cost_scenarios.json`
- `postmortem.md`
- `report.pdf`

## D. FINAL SUBMISSION CHECK

After the run:

```powershell
.\.venv\Scripts\python.exe -m src.final_check
python -m unittest discover -s tests -v
```

Open `report.pdf` and make sure the measured numbers look sensible. Then check that `.env` is not staged:

```powershell
git status
git check-ignore .env
```

`git check-ignore .env` should print `.env`.

Then commit the generated final evidence:

```powershell
git add .
git status
git commit -m "Complete Project 0 benchmark"
git push
```

Never use `git add -f .env`.
