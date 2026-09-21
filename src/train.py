"""Fine-tune Qwen 2.5 on the NHS medical abbreviation training dataset using LoRA / PEFT."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    parser = argparse.ArgumentParser(description="Fine-tune Qwen 2.5 on NHS abbreviations")
    parser.add_argument(
        "--model_name_or_path",
        type=str,
        default="Qwen/Qwen2.5-1.5B-Instruct",
        help="HuggingFace model identifier or local path",
    )
    parser.add_argument(
        "--train_data",
        type=str,
        default=str(ROOT / "data/train_sft.jsonl"),
        help="Path to training jsonl",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=str(ROOT / "models/qwen2.5-1.5b-nhs-lora"),
        help="Directory to save LoRA adapter",
    )
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=2, help="Per device batch size")
    parser.add_argument("--grad_accum", type=int, default=4, help="Gradient accumulation steps")
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--lora_rank", type=int, default=16, help="LoRA rank dimension")
    parser.add_argument("--lora_alpha", type=int, default=32, help="LoRA alpha scaling factor")
    return parser.parse_args()


def check_dependencies():
    missing = []
    for pkg in ["torch", "transformers", "peft", "datasets", "trl"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"Missing training dependencies: {', '.join(missing)}")
        print("To install required packages, run:")
        print("pip install torch transformers peft datasets trl accelerate bitsandbytes")
        return False
    return True


def train(args):
    if not check_dependencies():
        sys.exit(1)

    import torch
    from datasets import Dataset
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        TrainingArguments,
    )
    from trl import SFTTrainer

    print(f"Loading base model: {args.model_name_or_path}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    tokenizer = AutoTokenizer.from_pretrained(
        args.model_name_or_path,
        trust_remote_code=True,
        padding_side="right"
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Load dataset
    records = []
    with open(args.train_data, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    print(f"Loaded {len(records)} training records")

    # Format texts for SFT
    formatted_data = []
    for item in records:
        messages = item["messages"]
        text = tokenizer.apply_chat_template(messages, tokenize=False)
        formatted_data.append({"text": text})

    dataset = Dataset.from_list(formatted_data)

    # Model configuration
    model = AutoModelForCausalLM.from_pretrained(
        args.model_name_or_path,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True
    )

    lora_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )

    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        logging_steps=5,
        save_strategy="epoch",
        fp16=torch.cuda.is_available() and not (torch.cuda.is_bf16_supported()),
        bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=lora_config,
        dataset_text_field="text",
        max_seq_length=512,
        tokenizer=tokenizer,
        args=training_args,
    )

    print("Starting training...")
    trainer.train()

    print(f"Saving fine-tuned LoRA adapter to: {args.output_dir}")
    trainer.model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print("Training finished successfully!")


if __name__ == "__main__":
    args = parse_args()
    train(args)
