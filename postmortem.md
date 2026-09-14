# Postmortem

CS496 Project 0 | Final evidence: 14 September 2026 | Local Qwen bake-off

## What went wrong, and what we changed

**Our early practice task was easier than the final task.** We learned to
record the exact prompt and split rather than compare headline percentages.

**Case-sensitive scoring created false negatives.** The first 150-call test on
13 September accepted only three answers. Correctly worded, capitalized outputs
were rejected by the vocabulary check. We normalized outer whitespace and case

**Not every remaining failure is a scoring bug.** We inspected all 91 failed
responses in an AI-assisted diagnostic audit. Fourteen are spelling, spacing
or hyphen candidates, such as Fecal/faecal and High Density/high-density.

**The project accumulated duplication and stale documentation.** Practice and
final runs had separate loops, while setup instructions and result summaries
were scattered across files.

## What we learned and what remains

Qwen 7B is the accuracy preference at 54%, yet none meets the project's 95%
target. A larger model is not automatically adequate. Local inference avoids
API fees but still needs hardware and labour estimates. Repeated runs do not
increase the number of independent questions. Finally, our three-local-model
scope differs from API/API/local in the brief. Instructor acceptance and
any required empirical API comparison remain outstanding.

We split label preparation equally, then both Lassaad and Rami checked every
label, as confirmed by the team. An additional AI-assisted check on 14 September
matched all 60 labels to the NHS glossary using the documented canonical forms
and reviewed their contexts. It found no label/source mismatches and did not
change the scores or replace human review.
