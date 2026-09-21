"""Generate synthetic clinical instruction dataset from NHS medical abbreviation glossary."""

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_prompt_template():
    return (ROOT / "src/prompt.txt").read_text(encoding="utf-8")


def format_user_prompt(template, context, abbreviation):
    return template.format(context=context, abbreviation=abbreviation)


def generate_sft_dataset(output_path=None, seed=42):
    random.seed(seed)
    template = load_prompt_template()
    glossary_path = ROOT / "data/training_glossary.json"
    glossary = json.loads(glossary_path.read_text(encoding="utf-8"))

    records = []
    alpaca_records = []

    for item in glossary:
        abbrev = item["abbreviation"]
        expansion = item["expansion"]
        contexts = item.get("example_contexts", [])

        for ctx in contexts:
            prompt_text = format_user_prompt(template, ctx, abbrev)
            
            # ChatML / OpenAI messages format
            chat_record = {
                "messages": [
                    {"role": "user", "content": prompt_text},
                    {"role": "assistant", "content": expansion}
                ],
                "abbreviation": abbrev,
                "expected": expansion,
                "category": item.get("category", "")
            }
            records.append(chat_record)

            # Alpaca format
            alpaca_record = {
                "instruction": prompt_text,
                "input": "",
                "output": expansion
            }
            alpaca_records.append(alpaca_record)

    random.shuffle(records)
    random.shuffle(alpaca_records)

    out_file = output_path or (ROOT / "data/train_sft.jsonl")
    with open(out_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    alpaca_file = ROOT / "data/train_alpaca.json"
    alpaca_file.write_text(json.dumps(alpaca_records, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Generated {len(records)} training examples in {out_file.name} and {alpaca_file.name}")
    return records


if __name__ == "__main__":
    generate_sft_dataset()
