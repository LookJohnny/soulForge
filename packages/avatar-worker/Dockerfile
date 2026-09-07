# Reference build recipe; no model weights are included. GPU build/inference
# must be validated on the target host, not inferred from CPU protocol tests.
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    FLASHHEAD_REPO=/opt/flashhead \
    MODEL_DIR=/models/SoulX-FlashHead-1_3B \
    WAV2VEC_DIR=/models/wav2vec2-base-960h \
    AVATAR_SOURCE_IMAGE=/assets/avatar.png \
    MODEL_TYPE=pro \
    AVATAR_WORKER_HOST=0.0.0.0 \
    AVATAR_WORKER_PORT=8092 \
    MAX_JOBS=4

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3.10-venv build-essential git ca-certificates \
    ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN python3.10 -m venv /opt/worker-venv
ENV PATH=/opt/worker-venv/bin:$PATH
RUN python -m pip install --upgrade pip==25.1.1 setuptools==80.9.0 wheel==0.45.1

WORKDIR /opt/avatar-worker
COPY flashhead-revision.txt ./
COPY scripts/fetch_flashhead.sh ./scripts/fetch_flashhead.sh
RUN bash scripts/fetch_flashhead.sh "$FLASHHEAD_REPO"
RUN pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
RUN pip install -r "$FLASHHEAD_REPO/requirements.txt" ninja==1.11.1.4 \
    && pip install flash_attn==2.8.0.post2 --no-build-isolation
COPY pyproject.toml ./
COPY src ./src
RUN pip install .
EXPOSE 8092
CMD ["python", "-m", "avatar_worker"]
