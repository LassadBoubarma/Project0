# Postmortem

## What went wrong

The first pilot exposed a scoring problem: medically correct expansions that differed only in capitalisation were being marked wrong. For example, a model could return `Activated Partial Thromboplastin Time` while the gold label was `activated partial thromboplastin time`. We changed the scorer **before the final measured rerun** so that letter case and outer whitespace are ignored, while wording remains exact. We did not repair old outputs or selectively rescore favourable answers; the full 150-call benchmark was rerun under the final rule.

Even after that fix, exact canonical wording remains difficult. For example, qwen2.5:1.5b answered "Assessment and Management of People with Mental Health Problems" for AMHP, while the canonical label was "approved mental health professional". This is intentional for Project 0 because scoring must be automatic, but it means the benchmark measures both abbreviation knowledge and the ability to produce the chosen canonical expansion. The task also uses synthetic contexts and only 50 frozen test items, so one item changes accuracy by two percentage points.

## What we learned

The final results were: qwen2.5:1.5b: 16/50 (32.0%), p95 2399 ms; qwen2.5:3b: 16/50 (32.0%), p95 2428 ms; qwen2.5:7b: 27/50 (54.0%), p95 2454 ms. The highest measured accuracy was **qwen2.5:7b** at **27/50 (54.0%)**. The fastest p95 latency was **qwen2.5:1.5b** at **2399 ms**, and the lowest estimated local cost was **qwen2.5:1.5b** at **$5.0952 per 1,000 requests** under our stated hardware/labour assumptions.

The main lesson is that a larger model did not automatically make the engineering decision trivial. Model size changes quality, latency and generation throughput, and the scorer definition can affect measured accuracy substantially. Saving every per-item output made this visible instead of hiding it behind one percentage.

## What we would improve

A follow-up would create a separately versioned test set with more context-resolved abbreviations and more examples of terms that have several common expansions. We would freeze that new set before looking at model outputs and keep this run unchanged for reproducibility. We would also state the normalisation rule explicitly before any pilot: trim outer whitespace and compare case-insensitively, but reject different words, added explanations, multiline text, timeouts and malformed answers.

Finally, this experiment compares three self-hosted Qwen sizes on one machine. That is useful for studying the quality/speed/cost effect of model size, but it is not the same comparison as an API-vs-self-hosted bake-off. If the instructor requires the original API/API/local structure literally, that would need a separate run rather than rewriting these results after the fact.
