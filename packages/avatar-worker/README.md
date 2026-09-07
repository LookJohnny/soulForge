# SoulForge Avatar Worker

An independent Python service for one FlashHead source image and one CUDA GPU.
It consumes PCM produced by the existing SoulForge voice pipeline. It has no LLM,
ASR, TTS, persona store or memory, and does not download models at startup.

Implementation targets the official source commit
`9bc03de06bb0de82cd6bc477804512ae06144bf2`. Model weights and the wav2vec2 model
must already exist on the GPU host. No GPU inference has been run for this change.

See [deployment, protocol and acceptance instructions](../../docs/self-hosted-gpu-worker.md).

## Independent CPU protocol tests

These tests inject synthetic model outputs. They test the real HTTP routes,
sample alignment, JPEG adapter, authentication, backpressure and cancellation.
They do not measure model quality, GPU throughput, first-frame latency or a call.

```bash
cd packages/avatar-worker
python3.12 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

The GPU reference environment uses Python 3.10 / CUDA 12.8 / PyTorch 2.7.1 as in
the pinned upstream instructions. Keep this environment separate from the root
SoulForge `.venv`. This package is deliberately not a root workspace dependency.
