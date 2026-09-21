# Local hardware and model notes

- OS: Windows-11-10.0.26200-SP0
- CPU: AMD Ryzen 5 PRO 7540U w/ Radeon 740M Graphics
- GPU: AMD Radeon(TM) 740M
- RAM: 14.7 GB
- Python: 3.14.7

Models:
- qwen2.5:1.5b: digest 65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b; params 1.5B; quantisation Q4_K_M; generation 12.7 tokens/s
- qwen2.5:3b: digest 357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b; params 3.1B; quantisation Q4_K_M; generation 6.6 tokens/s
- qwen2.5:7b: digest 845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e; params 7.6B; quantisation Q4_K_M; generation 4.2 tokens/s

Cost assumptions:
- Hardware + electricity: $0.15/hour
- Operator time: 1 h/month at $5/h
- Baseline traffic: 1000 requests/month
