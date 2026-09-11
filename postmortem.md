# Postmortem — draft, complete after the real run

**Status:** implementation prepared; human review and the three-model experiment have not yet been performed. This is not a claim of a completed experiment.

**Problem encountered during preparation.** Medical abbreviations can have several meanings, and correct expansions can have different spellings. Unrestricted answers would mix semantic accuracy with formatting choices. The project therefore fixes a UK medical-record context and one vocabulary string per label. Each question includes a short synthetic context, and the same answer vocabulary is available to every model. This makes scoring repeatable, but may make the benchmark too easy.

**Measurement constraint.** The project authoring environment did not provide the student's API key or PC-hosted Ollama model. Consequently there are no real accuracy, latency or cost claims in the initial delivery. Header-only results files and a visibly marked draft report prevent offline validation from being mistaken for model evidence. Two human reviewers must also check the labels; AI-generated labels alone do not satisfy the assignment.

**Actual run problem — complete:** describe at least one observed issue, its evidence (run ID/item IDs/statuses), what caused it, and what you changed or would change. Keep failed responses in the archived run. Do not invent an outage or a model mistake. If there were no operational errors, discuss a genuine limitation revealed by the measured results, such as saturation, strict formatting failures or wide local latency variation.

**What we learned — complete:** explain the measured trade-off between exact accuracy, p95 latency and cost, with at least two numbers. State which model you chose and what would cause you to change that choice. Distinguish list-price estimates from an actual invoice, and specify the hardware and operator-time assumptions.

**Next improvement — complete:** propose one concrete change supported by your failures, such as a separately versioned harder test set or more repeated timing runs. State the limitation of a 50-item convenience sample and why test answers must not be edited after seeing model outputs.
