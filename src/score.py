"""Deterministic case-insensitive exact scorer. No LLM judge or output repair."""


def score(output, expected, word_list):
    """Score one model response.

    Policy:
    - ignore outer whitespace;
    - ignore letter case (case-insensitive exact match);
    - still require exactly one line;
    - still require the answer to match one canonical vocabulary entry after case-folding;
    - do not accept synonyms, extra explanations, punctuation, stemming or fuzzy matches.
    """
    answer = output.strip()
    # Fixed, transparent refusal markers; unknown wording remains a parse error.
    refusal_prefixes = (
        "i cannot",
        "i can't",
        "i am unable",
        "i'm unable",
        "sorry, i cannot",
        "sorry, i can't",
        "i cannot provide",
    )
    if answer.casefold().startswith(refusal_prefixes):
        return 0, "refusal", answer
    if not answer or "\n" in answer or "\r" in answer:
        return 0, "parse_error", answer

    answer_key = answer.casefold()
    vocabulary_keys = {term.casefold() for term in word_list}
    if answer_key not in vocabulary_keys:
        return 0, "parse_error", answer

    expected_key = expected.strip().casefold()
    return (
        int(answer_key == expected_key),
        "correct" if answer_key == expected_key else "wrong_answer",
        answer,
    )
