# Labelling and dataset policy

Source: [NHS, Understanding abbreviations](https://www.nhs.uk/nhs-app/help/understanding-abbreviations/), accessed 11 September 2026. These are factual abbreviation/meaning mappings. The 60 contexts are original synthetic sentences drafted with AI assistance; no real patient data are used. NHS warns that abbreviations may have different meanings in different settings; this benchmark explicitly uses UK medical records and provides context.

There are 10 development examples (`dev.jsonl`) and 50 test examples (`items.jsonl`). Their abbreviations do not overlap. The split is a fixed convenience split, not a random population sample: the familiar terms are in dev and rarer terms in test. Thus dev accuracy is not an unbiased estimate of test difficulty. Dev is only for setup/prompt checks. Do not tune on final test outcomes.

Labels use one canonical form: dictionary parenthetical explanations are omitted; initial capitalisation is reduced to lower case except the established `X-ray` form. The fixed word list gives the exact spellings before scoring and contains both development and test labels. It does not reveal which abbreviation maps to which string. This is a constrained expansion task, rather than an unconstrained synonym test. No aliases, stemming, case folding, fuzzy matching or LLM judgement are accepted. For example `blood pressure` matches; `Blood pressure` and `BP means blood pressure.` do not.

Review protocol, not a claim of completed review:

1. Reviewer 1 checks each abbreviation, context, unique interpretation and canonical label against the source.
2. Reviewer 2 independently checks the same items without copying the first reviewer's judgement.
3. Resolve disagreements before the test run. If the source does not support a clear single answer, revise context or replace the item before freezing; record the reason.
4. Enter both real reviewer names and the actual date in `label_reviews.csv`. Blank fields in this delivery deliberately show that the review is pending. AI drafting and source checking do not count as two human reviewers.
5. Freeze the dataset, vocabulary and prompt before evaluating the test split. The runner saves hashes and the full question list. Never delete failed items or repair responses by hand.

The set covers diagnostic tests, nursing notation, staff roles, resuscitation decisions and medicine formulations. Staff roles such as PT/OT/POD and notation such as Ix/Hx require the supplied context. Similar labels such as DNAR/DNR/DNACPR are intentionally retained. The task is likely easier with the supplied vocabulary, so saturation must be assessed honestly. Pilot results have not yet been measured. If a new dataset is required after a test run, archive the original and label the follow-up as a new experiment.
