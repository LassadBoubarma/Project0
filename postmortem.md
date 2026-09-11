# Postmortem - draft

The final three-model benchmark has not been run yet, so this file does not invent a problem or a lesson. After the real 50-item test, `src/report.py` automatically replaces this draft with a postmortem grounded in the measured failures (or, if every model is perfect, the genuine saturation limitation), measured accuracy, p95 latency and cost.

Until then, the genuine preparation issue is that medical abbreviations can have multiple meanings and multiple spellings. This project controls that risk by fixing a UK medical-record context, using one NHS-backed canonical answer per item, supplying one common output vocabulary, and requiring two independent human label reviews before the final test.
