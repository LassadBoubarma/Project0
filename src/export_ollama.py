"""Export fine-tuned model or create specialized Ollama Modelfile for NHS medical abbreviation evaluation."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    parser = argparse.ArgumentParser(description="Export fine-tuned model to Ollama")
    parser.add_argument(
        "--adapter_dir",
        type=str,
        default=str(ROOT / "models/qwen2.5-1.5b-nhs-lora"),
        help="Path to trained LoRA adapter",
    )
    parser.add_argument(
        "--base_model",
        type=str,
        default="Qwen/Qwen2.5-1.5B-Instruct",
        help="Base model used during fine-tuning",
    )
    parser.add_argument(
        "--ollama_base_model",
        type=str,
        default="qwen2.5:1.5b",
        help="Ollama base model name",
    )
    parser.add_argument(
        "--target_model_name",
        type=str,
        default="qwen2.5-1.5b-nhs",
        help="Target Ollama model name to register",
    )
    parser.add_argument(
        "--modelfile_path",
        type=str,
        default=str(ROOT / "Modelfile"),
        help="Path where Modelfile should be written",
    )
    return parser.parse_args()


def merge_and_save_hf(base_model_name, adapter_dir, merged_output_dir):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"Loading base model: {base_model_name}")
    tokenizer = AutoTokenizer.from_pretrained(adapter_dir, trust_remote_code=True)
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        torch_dtype=torch.float16,
        device_map="auto" if torch.cuda.is_available() else "cpu",
        trust_remote_code=True,
    )

    print(f"Applying LoRA adapter from: {adapter_dir}")
    model = PeftModel.from_pretrained(base_model, adapter_dir)
    merged_model = model.merge_and_unload()

    print(f"Saving merged model to: {merged_output_dir}")
    merged_model.save_pretrained(merged_output_dir)
    tokenizer.save_pretrained(merged_output_dir)
    print("Merged model saved successfully!")


def create_modelfile(ollama_base_model, modelfile_path, adapter_path=None):
    """Generate an optimized Ollama Modelfile tailored for UK NHS medical abbreviation expansion."""
    system_instruction = (
        "You are an expert UK NHS clinical informatics assistant. "
        "Your task is to accurately expand medical abbreviations found in UK medical records into their exact canonical British English full terms. "
        "Always output ONLY the lowercase full medical term on a single line with no punctuation, no quotes, no labels, and no explanation."
    )

    content = f"""FROM {ollama_base_model}

SYSTEM \"\"\"{system_instruction}\"\"\"

PARAMETER temperature 0
PARAMETER num_predict 64
PARAMETER stop "<|im_end|>"
PARAMETER stop "\\n"
"""
    if adapter_path and Path(adapter_path).exists():
        content += f"\nADAPTER {adapter_path}\n"

    Path(modelfile_path).write_text(content, encoding="utf-8")
    print(f"Created Modelfile at: {modelfile_path}")
    return modelfile_path


def register_ollama_model(model_name, modelfile_path):
    print(f"Registering model '{model_name}' in Ollama...")
    result = subprocess.run(
        ["ollama", "create", model_name, "-f", str(modelfile_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"Successfully registered '{model_name}' with Ollama!")
        print(result.stdout)
    else:
        print(f"Ollama registration output/error: {result.stderr or result.stdout}")
    return result.returncode == 0


def main():
    args = parse_args()
    adapter_path = Path(args.adapter_dir)
    
    if adapter_path.exists():
        print(f"Found trained adapter in {adapter_path}")
        modelfile = create_modelfile(args.ollama_base_model, args.modelfile_path, adapter_path=str(adapter_path))
    else:
        print(f"No local adapter directory found at {adapter_path}. Creating optimized NHS Modelfile from base model {args.ollama_base_model}...")
        modelfile = create_modelfile(args.ollama_base_model, args.modelfile_path)

    register_ollama_model(args.target_model_name, modelfile)


if __name__ == "__main__":
    main()
