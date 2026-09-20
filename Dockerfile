# ComfyUI container image for the gputw service.
# amd64-only. Build with `docker buildx build --platform=linux/amd64 ...`.
# Pin a ComfyUI release at build time via COMFYUI_VERSION.

ARG COMFYUI_VERSION=v0.36.0
ARG PYTORCH_CUDA_TAG=cu128
ARG CUDA_BASE_IMAGE=nvidia/cuda:12.8.0-runtime-ubuntu22.04
ARG COMFYUI_PORT=8080
ARG COMFYUI_CPU=0

FROM --platform=linux/amd64 ${CUDA_BASE_IMAGE}

ARG COMFYUI_VERSION
ARG PYTORCH_CUDA_TAG
ARG COMFYUI_PORT
ARG COMFYUI_CPU
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COMFYUI_HOME=/opt/comfyui \
    COMFYUI_PORT=${COMFYUI_PORT} \
    COMFYUI_CPU=${COMFYUI_CPU} \
    HF_HUB_ENABLE_HF_TRANSFER=1

# OS deps: python3 (Ubuntu 22.04 ships 3.10), libgl/libsm/libxext for Pillow/OpenCV,
# ffmpeg for video custom nodes (e.g. VideoHelperSuite), unzip for fetching ComfyUI.
# gcc + python3-dev: required by Triton JIT at runtime (torch 2.13 _native dispatch
# compiles kernels on first use; missing compiler fails inference).
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv python3-dev \
        gcc \
        ca-certificates curl wget git unzip \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Fetch ComfyUI source as a zip — no .git history, smaller download and build context.
# COMFYUI_VERSION may be a tag (v0.36.0) or a commit SHA (for unreleased features);
# the generic /archive/<ref>.zip endpoint resolves both. The extracted dir is
# ComfyUI-<ref-without-leading-v> for tags, but GitHub expands short SHAs to the
# full 40-char SHA — so match the single extracted dir with a glob.
WORKDIR /opt
RUN curl -fsSL -o comfyui.zip \
        https://github.com/Comfy-Org/ComfyUI/archive/${COMFYUI_VERSION}.zip \
    && unzip -q comfyui.zip \
    && mv ComfyUI-* ${COMFYUI_HOME} \
    && rm comfyui.zip

WORKDIR ${COMFYUI_HOME}

# Bundled workflows: baked into ComfyUI's DEFAULT user directory so they appear in the
# UI workflow panel out of the box. Only visible when launched WITHOUT --user-directory
# (vast.ai). GPUtw launches with --user-directory /vault/... and manages its own.
COPY workflows/ ${COMFYUI_HOME}/user/default/workflows/

# Install PyTorch first (${PYTORCH_CUDA_TAG} wheel) so ComfyUI's requirements.txt cannot downgrade it.
RUN pip install --no-cache-dir \
        torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/${PYTORCH_CUDA_TAG} \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir hf hf-transfer

EXPOSE ${COMFYUI_PORT}

# gputw should mount model / output volumes at these paths so artifacts survive restarts.
VOLUME ["/opt/comfyui/models", "/opt/comfyui/output"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fsS http://localhost:${COMFYUI_PORT}/system_stats || exit 1

# shell form so ${COMFYUI_PORT} and ${COMFYUI_CPU} get substituted; python still handles SIGTERM via sh.
# COMFYUI_CPU=1 forces ComfyUI's --cpu flag so the image can boot on a host without a GPU (smoke test only).
# Use python3 (no /usr/bin/python symlink exists in this base image).
CMD python3 main.py --listen 0.0.0.0 --port ${COMFYUI_PORT} $([ "${COMFYUI_CPU}" = "1" ] && echo --cpu)
