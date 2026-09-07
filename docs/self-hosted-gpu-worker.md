# Self-hosted FlashHead GPU worker

Status, 2026-09-07: source adapter and offline protocol tests implemented. No
checkpoint download, Docker build, CUDA inference, paid GPU job, video-quality
evaluation or live browser call has been performed. A running CPU HTTP service
with `ready:false` is not a working avatar renderer.

## Source and actual inference contract

Official repository: [Soul-AILab/SoulX-FlashHead](https://github.com/Soul-AILab/SoulX-FlashHead),
pinned to `9bc03de06bb0de82cd6bc477804512ae06144bf2`.
The adapter calls `get_pipeline(world_size=1, ...)`, `get_base_data(...)`,
`get_infer_params()`, `get_audio_embedding(...)` and `run_pipeline(...)`.
Source image preparation is performed once. Each render request resets the
official `pipeline.reset_person_name()`, random seed and 8-second audio deque.
It does not reload model weights for each utterance.

The source's `infer_params.yaml` sets 16 kHz audio, 25 FPS, 33 model frames and
two latent motion frames. `get_pipeline()` derives pixel-frame overlap from the
actual loaded model's temporal VAE stride. The worker validates this result.

| Model | Internal frames | Historical overlap dropped on **every** block | Delivered frames | PCM samples per block | Block duration |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pro | 33 | 5 | 28 | 17,920 | 1.12 s |
| Lite | 33 | 9 | 24 | 15,360 | 0.96 s |

This includes the first streaming block. Emitting all 33 frames with only
28/24 frames' worth of audio causes systematic drift. The rolling audio window
has 128,000 samples; the embedding uses video-frame positions `[167, 200)`.
Each JPEG is RGB 512×512. No MP4 bundling delays are added by this worker.

The official Gradio stream groups three blocks into an MP4 segment; this worker
does not use Gradio. A request still contains a complete padded audio payload:
NDJSON output is incremental, but incoming audio is not streamed. The worker
also resets motion between requests, so it does not yet provide a continuous
listening body across separate utterances.

## API

The service defaults to `127.0.0.1:8092`. Keep it private or put a TLS gateway in
front; never expose the server token to the browser. One OS process and one
Uvicorn worker are required. Horizontal replicas need independent GPU allocation.

`GET /health` requires no credential and reports `configured`, `ready`, `status`,
`model`, source `revision`, `cuda_available`, `reason`, `block_samples`,
`frames_per_chunk`, `max_audio_samples`, `sample_rate`, `fps`, `busy` and counters.
It does not return tokens or local model/image paths. `configured` means fields
are present; `ready` means setup succeeded. First inference may still include
compilation, and neither field proves real-time performance or visual quality.

Capabilities explicitly advertise only audio-driven portraits and streaming
output. Gaze, emotion, body controls, multi-GPU HTTP serving and cross-request
motion continuity are false. No supported-control claims are inferred from
arbitrary JSON fields.

`POST /render` requires `Authorization: Bearer <AVATAR_WORKER_TOKEN>`:

```json
{
  "request_id": "utterance-uuid-or-epoch-id",
  "audio_base64": "base64 of raw PCM16LE, mono, 16000 Hz",
  "sample_rate": 16000
}
```

Only these three fields are accepted. The caller must pad with zero PCM samples
to a multiple of the current health response's `block_samples`, and preserve the
original sample count separately. The worker rejects partial blocks; it never
silently drops or pads input. The maximum is a 120-second utterance rounded up
to the next whole block, exposed as `max_audio_samples`.

Successful responses use `application/x-ndjson`. Each line is a JSON object:

```json
{"type":"chunk","request_id":"utterance-id","chunk_seq":0,"start_sample":0,"sample_count":17920,"sample_rate":16000,"fps":25,"frames":["base64 JPEG"],"frame_count":28}
{"type":"done","request_id":"utterance-id","chunk_count":1,"total_samples":17920,"total_frames":28,"sample_rate":16000,"fps":25}
```

The example abbreviates `frames`; a Pro chunk really contains 28 JPEG strings.
`start_sample` is relative to this request, beginning at zero. Frame `i` covers
`start_sample + i*640` through the next 640 samples at 25 FPS. The invariant is
`sample_count * fps == frame_count * sample_rate`. The caller must play the
**same PCM** it sent to the worker and stop audio at its original sample count;
do not play zero padding or stretch a full final video chunk over trimmed audio.
Drop frames wholly beyond the original tail, and bound the last partial frame
to the end-of-audio timestamp in the media scheduler.

HTTP errors: 401 invalid token, 413 oversized body, 422 invalid format or partial
block, 429 busy, 503 not ready. If inference fails after headers were sent, a
`type:error` line with a fixed code and exception **type only** replaces `done`;
the worker becomes not ready. No fake frame or success fallback is emitted.
`done` means generated output finished; it is not an audio/video playback ACK.

Disconnect cancels between blocks. A running CUDA kernel cannot be safely
aborted: its result is discarded, and the busy slot remains occupied until it
finishes. The producer uses bounded backpressure and checks cancellation before
starting another block. The media body must also clear its own audio/video
queues and reject late frames from an old request/epoch. Replacing the request
ID alone does not cancel a GPU operation or browser playback.

## Isolated single-GPU deployment

Required environment variables are documented in
[`packages/avatar-worker/.env.example`](../packages/avatar-worker/.env.example).
`MODEL_DIR` is the root with `Model_Pro` + `VAE_Wan`, or `Model_Lite` + `VAE_LTX`;
`WAV2VEC_DIR` is a local `facebook/wav2vec2-base-960h` checkpoint directory.
`AVATAR_SOURCE_IMAGE` is a prepared, authorized single portrait, not a directory.
The adapter disables face cropping rather than silently accepting a failed crop.

On a provisioned Linux NVIDIA host, the following source-only step pins the
checkout and avoids upstream demo media/LFS assets:

```bash
cd packages/avatar-worker
bash scripts/fetch_flashhead.sh /opt/SoulX-FlashHead
```

Model acquisition is a separate explicit operator step on that host. The
official model repositories are
[SoulX-FlashHead-1_3B](https://huggingface.co/Soul-AILab/SoulX-FlashHead-1_3B)
and [wav2vec2-base-960h](https://huggingface.co/facebook/wav2vec2-base-960h).
Record the exact weight revisions with the acceptance results; this change pins
source, not remotely downloaded weight revisions. No model downloader is invoked
by the server, image build or source fetch script.

The independent container recipe follows upstream Python 3.10, PyTorch 2.7.1 /
torchvision 0.22.1 CUDA 12.8, xformers 0.0.31 and FlashAttention 2.8.0.post2.
It installs the pinned source's requirements. Some upstream transitive
dependencies use open ranges, so this is a reference build, not a fully resolved
reproducible dependency lock. Save `pip freeze` and the resulting image digest
when the GPU-host build is validated. Do not install these into SoulForge's root
environment.

```bash
docker build -t soulforge-avatar-worker:flashhead-9bc03de packages/avatar-worker
# worker.env contains AVATAR_WORKER_TOKEN only; protect it with chmod 600.
# Keep published access local; tunnel privately or terminate TLS on the host.
docker run --rm --gpus '"device=0"' \
  --env-file /private/config/worker.env \
  -e MODEL_TYPE=pro \
  -p 127.0.0.1:8092:8092 \
  -v /srv/avatar-models:/models:ro \
  -v /srv/avatar-assets:/assets:ro \
  soulforge-avatar-worker:flashhead-9bc03de
```

The source checks require the exact clean commit. `WORLD_SIZE>1` is rejected.
GPU drivers/NVIDIA Container Toolkit and sufficient model memory must be present
on the host. The image is a CUDA **devel** base because FlashAttention may compile.
No hardware throughput or memory-fit claim follows from this unbuilt recipe.

### Pro quality baseline, then Lite speed comparison

Use the official offline generator inside the same image for a Pro quality
baseline, with already mounted source portrait and 16 kHz WAV:

```bash
# Inside a single-GPU container with the same /models and /assets mounts:
cd /opt/flashhead
python generate_video.py \
  --ckpt_dir "$MODEL_DIR" --wav2vec_dir "$WAV2VEC_DIR" \
  --model_type pro --cond_image "$AVATAR_SOURCE_IMAGE" \
  --audio_path /assets/acceptance-16k-mono.wav \
  --audio_encode_mode stream --save_file /tmp/pro-baseline.mp4
```

Then restart this worker with `MODEL_TYPE=lite`; callers must re-read health and
switch padding to 15,360 samples. Use identical portrait/audio and measure
first-chunk latency, sustained generation time per block, CUDA peak memory and
observable mouth/voice alignment. Lite is the official single-GPU real-time
candidate; this service has not demonstrated real-time performance on a GPU.

The upstream repository includes a genuine Pro `torchrun` multi-GPU script and
USP/NCCL setup. The HTTP worker intentionally only calls `world_size=1`; setting
an environment variable does not convert it into a distributed service. Do not
run several Uvicorn workers on one GPU or describe this worker as multi-GPU Pro.

## Validation boundary

Offline tests inject fake model tensors and check actual HTTP serialization,
authorization, sample slicing, JPEG encoding, overlap removal, cancellation,
busy-slot ownership and explicit not-ready/error states. They cannot verify
checkpoint compatibility, CUDA memory fit, compiled inference, motion quality,
naturalness, browser WebRTC synchronization or real interruption latency.

Before selecting hardware or replacing the current face provider, verify one
real vertical slice: generated speech and face together, interruption discards
both, then contextual continuation. Record the actual source/weight revisions,
GPU, driver, package lock and timings. No separate brain may be inserted here.
