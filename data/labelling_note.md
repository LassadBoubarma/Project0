# Labelling and dataset policy

Source: [NHS, Understanding abbreviations](https://www.nhs.uk/nhs-app/help/understanding-abbreviations/), accessed 11 September 2026. These are factual abbreviation/meaning mappings. The 60 contexts are original synthetic sentences drafted with AI assistance; no real patient data are used. NHS warns that abbreviations may have different meanings in different settings; this benchmark explicitly uses UK medical records and provides context.

There are 10 development examples (`dev.jsonl`) and 50 test examples (`items.jsonl`). Their abbreviations do not overlap. The split is a fixed convenience split, not a random population sample: the familiar terms are in dev and rarer terms in test. Thus dev accuracy is not an unbiased estimate of test difficulty. Dev is only for setup/prompt checks. Do not tune on final test outcomes.

Labels use one canonical form: dictionary parenthetical explanations are omitted; initial capitalisation is reduced to lower case except the established `X-ray` form. The fixed word list contains the canonical spellings used by the deterministic scorer and contains both development and test labels. **It is not shown to any model.** The model receives only the context, abbreviation and output-format instruction. This is therefore a hidden-answer exact-expansion task, not multiple choice. Letter case is ignored during scoring, but wording is otherwise exact. No aliases, stemming, fuzzy matching or LLM judgement are accepted. For example `blood pressure`, `Blood Pressure` and `BLOOD PRESSURE` all match the canonical answer `blood pressure`; `BP means blood pressure.` does not.

The team confirms that Lassaad and Rami each checked all 60 labels. Preparation was split equally, but both reviewed the full dataset. The supplied CSV already records both names for every item; its original review date of 2026-09-11 is preserved. Human review is reported by the team, not independently verified by AI. The protocol is:

1. Reviewer 1 checks each abbreviation, context, unique interpretation and canonical label against the source.
2. Reviewer 2 independently checks the same items without copying the first reviewer's judgement.
3. Resolve disagreements before the test run. If the source does not support a clear single answer, revise context or replace the item before freezing; record the reason.
4. Enter both real reviewer names and the actual date in `label_reviews.csv`. Missing or duplicate reviewer names block a new final run. AI drafting and source checking do not count as two human reviewers.
5. Freeze the dataset, vocabulary and prompt before evaluating the test split. The runner saves hashes and the full question list. Never delete failed items or repair responses by hand.

An additional AI-assisted source check on 2026-09-14 compared all 60 labels with the NHS glossary: 60 matched after omitting parenthetical explanations and ignoring case and surrounding whitespace as documented. All contexts were also read for consistency with their intended meanings; no conflicts were found. No labels or scores were changed. This check supplements, rather than replaces, the two human reviews.

The set covers diagnostic tests, nursing notation, staff roles, resuscitation decisions and medicine formulations. Staff roles such as PT/OT/POD and notation such as Ix/Hx require the supplied context. Similar labels such as DNAR/DNR/DNACPR are intentionally retained. Showing the vocabulary to models would change the task; it remains hidden. The included final run is identified by `results/latest_run.txt` and contains 150 responses. If a new dataset is required after a test run, archive the original and label the follow-up as a new experiment.
