"""One deterministic parser for every model. No LLM judge or output repair."""

def score(output, expected, word_list):
    # Only transport whitespace around the whole response is ignored.
    answer = output.strip()
    if not answer or '\n' in answer or '\r' in answer or answer not in word_list:
        return 0, 'parse_error', answer
    return int(answer == expected), 'correct' if answer == expected else 'wrong_answer', answer
