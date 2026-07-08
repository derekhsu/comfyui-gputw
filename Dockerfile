# ComfyUI container image for the gputw service.
# amd64-only. Build with `docker buildx build --platform=linux/amd64 ...`.
# Pin a ComfyUI release at build time via COMFYUI_VERSION.

ARG COMFYUI_VERSION=v0.27.0
ARG PYTORCH_CUDA_TAG=cu128
ARG COMFYUI_PORT=8080
ARG COMFYUI_CPU=0

FROM --platform=linux/amd64 nvidia/cuda:12.8.0-runtime-ubuntu22.04

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
    COMFYUI_CPU=${COMFYUI_CPU}

# OS deps: python3 (Ubuntu 22.04 ships 3.10), libgl for Pillow/OpenCV, unzip for fetching ComfyUI.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        ca-certificates curl wget git unzip \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Fetch ComfyUI source as a zip — no .git history, smaller download and build context.
WORKDIR /opt
RUN curl -fsSL -o comfyui.zip \
        https://github.com/Comfy-Org/ComfyUI/archive/refs/tags/${COMFYUI_VERSION}.zip \
    && unzip -q comfyui.zip \
    && mv ComfyUI-${COMFYUI_VERSION#v} ${COMFYUI_HOME} \
    && rm comfyui.zip

WORKDIR ${COMFYUI_HOME}

# Install PyTorch first (${PYTORCH_CUDA_TAG} wheel) so ComfyUI's requirements.txt cannot downgrade it.
RUN pip install --no-cache-dir \
        torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/${PYTORCH_CUDA_TAG} \
    && pip install --no-cache-dir -r requirements.txt

EXPOSE ${COMFYUI_PORT}

# gputw should mount model / output volumes at these paths so artifacts survive restarts.
VOLUME ["/opt/comfyui/models", "/opt/comfyui/output"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fsS http://localhost:${COMFYUI_PORT}/system_stats || exit 1

# shell form so ${COMFYUI_PORT} and ${COMFYUI_CPU} get substituted; python still handles SIGTERM via sh.
# COMFYUI_CPU=1 forces ComfyUI's --cpu flag so the image can boot on a host without a GPU (smoke test only).
# Use python3 (no /usr/bin/python symlink exists in this base image).
CMD python3 main.py --listen 0.0.0.0 --port ${COMFYUI_PORT} $([ "${COMFYUI_CPU}" = "1" ] && echo --cpu)