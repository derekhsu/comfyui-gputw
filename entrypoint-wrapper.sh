#!/bin/sh
# Entrypoint for comfyui-gputw custom image.
#
# This script is the image ENTRYPOINT (not CMD) so it ALWAYS runs, even
# when gpuai replaces CMD with user-provided startup arguments. It:
#   1. Loads secrets from /vault/secrets/ (gpuai env vars take priority)
#   2. Symlinks LoraManager settings.json from the vault
#   3. Builds the default ComfyUI command and APPENDS any gpuai-provided
#      startup args as extra parameters
#   4. exec's nvidia_entrypoint.sh (the base image's original entrypoint)
#      which sets up the CUDA env and then runs the actual command
#
# gpuai startup arguments replace CMD, so they arrive as "$@". They are
# appended to the default ComfyUI invocation so users only need to pass
# the flags they want to add or override (e.g. --port 9000).
#
# Secrets priority:
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

# 3. Build the command to run.
#    The default ComfyUI invocation is ALWAYS used as the base command,
#    and any gpuai-provided startup args ($@) are APPENDED as extra
#    parameters. This lets users pass just the flags they want to tweak
#    (e.g. --port 9000) without rewriting the whole command.
#    ComfyUI's argparse takes the last value for repeated options, so
#    overriding --port etc. by passing it again works as expected.
#    To run an arbitrary command (e.g. a shell) instead of ComfyUI,
#    bypass the wrapper with `docker run --entrypoint <cmd> ...`.
#    We then exec nvidia_entrypoint.sh — the base image's original
#    ENTRYPOINT — which sets up the CUDA env (PATH, LD_LIBRARY_PATH, etc.)
#    before exec'ing the command. This preserves GPU support while
#    guaranteeing secrets are loaded regardless of whether gpuai set CMD.
set -- python3 main.py --listen 0.0.0.0 --port "${COMFYUI_PORT}" $([ "${COMFYUI_CPU}" = "1" ] && echo --cpu) "$@"
# Full path required: nvidia_entrypoint.sh lives in /opt/nvidia/ which is
# NOT in PATH (only /opt/nvidia/bin is, for nvidia-smi).
exec /opt/nvidia/nvidia_entrypoint.sh "$@"
