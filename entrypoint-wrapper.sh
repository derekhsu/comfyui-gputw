#!/bin/sh
# Entrypoint wrapper for comfyui-gputw custom image.
#
# gpuai does not support runtime env vars or volume mounts (beyond /vault),
# so secrets that ComfyUI and its custom nodes need (HuggingFace token,
# CivitAI API key, etc.) are loaded from /vault/secrets/ at startup.
#
# Files consumed (all optional — missing files are silently skipped):
#   /vault/secrets/env.sh                       — sourced as shell env vars
#                                                 (e.g. export HF_TOKEN=...)
#   /vault/secrets/lora-manager-settings.json   — symlinked into
#                                                 ComfyUI-Lora-Manager/settings.json

# 1. Source env vars (HuggingFace token, etc.)
if [ -f /vault/secrets/env.sh ]; then
    echo "[entrypoint] Loading secrets from /vault/secrets/env.sh"
    . /vault/secrets/env.sh
fi

# 2. Symlink LoraManager settings.json (contains civitai_api_key)
LORA_MANAGER_DIR="${COMFYUI_HOME}/custom_nodes/ComfyUI-Lora-Manager"
if [ -d "$LORA_MANAGER_DIR" ] && [ -f /vault/secrets/lora-manager-settings.json ]; then
    echo "[entrypoint] Linking LoraManager settings from /vault/secrets/"
    ln -sf /vault/secrets/lora-manager-settings.json "$LORA_MANAGER_DIR/settings.json"
fi

# 3. Start ComfyUI (same invocation as the base image CMD).
#    exec so python3 replaces this shell and receives SIGTERM directly.
exec python3 main.py --listen 0.0.0.0 --port ${COMFYUI_PORT} $([ "${COMFYUI_CPU}" = "1" ] && echo --cpu)
