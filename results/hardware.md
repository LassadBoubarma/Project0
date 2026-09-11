# Local hardware — complete on the PC running Ollama

Status: pending. This file must describe your actual machine, not the machine that generated the project files.

- CPU:
- GPU and VRAM (or state CPU-only):
- RAM:
- Operating system:
- Ollama version (`ollama --version`):
- Exact model, parameter count, quantisation (`ollama show qwen2.5:1.5b`):
- Model digest (automatically recorded in the run metadata):
- Hardware/electricity cost in USD/hour and calculation/source:
- Operator setup/maintenance hours allocated per month and hourly value:
- Available serving hours/month (config default 160; justify/change before run):
- Other workloads/power mode during measurement:
- Any model loading, thermal throttling or memory problems:

For an owned machine, one possible hardware model is purchase price / expected useful operating hours + measured kW × electricity tariff. Those inputs must come from your situation. Do not use an invented GPU rental price. Local tokens/s and request throughput are generated from actual response timings. Cold first-call loading is included in latency; downloaded model weights are fetched before the run.
