# Local hardware - pending final run

The final runner will overwrite this file with hardware/model information captured from the computer running Ollama, plus the cost assumptions from `config.json`.

Before the final test, fill these real values in `config.json` under `local_cost`:

- `hardware_usd_per_hour`
- `labour_hours_per_month`
- `labour_usd_per_hour`

Do not invent a cloud/GPU rental price if you are using your own PC. A reasonable owned-PC method is depreciation per operating hour plus electricity cost per hour, with operator time entered separately.
