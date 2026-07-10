#!/bin/sh
# Entrypoint wrapper for comfyui-gputw custom image.
#
# Loads secrets (HuggingFace token, CivitAI API key, etc.) at startup.
# gpuai now supports runtime env vars in the deploy form, so there are
# two ways to provide secrets, with gpuai env vars taking priority:
#
#   1. gpuai deploy-form env vars (e.g. HF_TOKEN=hf_xxx) — highest priority
#   2. /vault/secrets/env.sh — fallback for vars not set by gpuai
#
# For LoraManager's settings.json (a JSON file, not a single env var),
# we symlink from /vault/secrets/ since env vars can't carry JSON.
#
# Files consumed (all optional — missing files are silently skipped):
#   /vault/secrets/env.sh                       — sourced as shell env vars
#                                                 (e.g. export HF_TOKEN=...)
#   /vault/secrets/lora-manager-settings.json   — symlinked into
#                                                 ComfyUI-Lora-Manager/settings.json

# 1. Load env vars from vault, but let gpuai deploy-form env vars win.
#    Strategy: snapshot the known secret vars BEFORE sourcing env.sh,
#    source env.sh, then restore the snapshotted values (if any).
#    Add new secret var names to SECRETS_VARS as needed.
SECRETS_VARS="HF_TOKEN HUGGING_FACE_HUB_TOKEN CIVITAI_API_KEY"
# Save current values (empty if unset)
for _v in $SECRETS_VARS; do
    eval "_saved_$_v=\${$_v:-}"
done
if [ -f /vault/secrets/env.sh ]; then
    echo "[entrypoint] Loading secrets from /vault/secrets/env.sh"
    . /vault/secrets/env.sh
fi
# Restore gpuai-provided values (override anything env.sh set)
for _v in $SECRETS_VARS; do
    eval "_saved=\$_saved_$_v"
    if [ -n "$_saved" ]; then
        eval "export $_v=\$_saved"
    fi
done

# 2. Symlink LoraManager settings.json (contains civitai_api_key)
LORA_MANAGER_DIR="${COMFYUI_HOME}/custom_nodes/ComfyUI-Lora-Manager"
if [ -d "$LORA_MANAGER_DIR" ] && [ -f /vault/secrets/lora-manager-settings.json ]; then
    echo "[entrypoint] Linking LoraManager settings from /vault/secrets/"
    ln -sf /vault/secrets/lora-manager-settings.json "$LORA_MANAGER_DIR/settings.json"
fi

# 3. Start ComfyUI (same invocation as the base image CMD).
#    exec so python3 replaces this shell and receives SIGTERM directly.
exec python3 main.py --listen 0.0.0.0 --port ${COMFYUI_PORT} $([ "${COMFYUI_CPU}" = "1" ] && echo --cpu)
