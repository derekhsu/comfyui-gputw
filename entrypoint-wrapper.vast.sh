#!/bin/sh
# Entrypoint for comfyui-gputw vast.ai image.
#
# This script is the image ENTRYPOINT (not CMD) so it ALWAYS runs, even
# when vast.ai passes user-provided arguments via the Entrypoint launch
# mode (--args). It:
#   1. Loads secrets from /data/secrets/ (vast.ai env vars take priority)
#   2. Seeds LoraManager settings.json into ~/.config from the volume
#   3. Builds the default ComfyUI command and APPENDS any user-provided
#      args as extra parameters
#   4. exec's nvidia_entrypoint.sh (the base image's original entrypoint)
#      which sets up the CUDA env and then runs the actual command
#
# vast.ai launch mode notes:
#   - Use the "docker ENTRYPOINT" launch mode. SSH/Jupyter launch modes
#     REPLACE the entrypoint with vast.ai's setup script, so this wrapper
#     would NOT run and secrets would NOT be loaded.
#   - In Entrypoint launch mode, extra --args arrive as "$@" and are
#     appended to the default ComfyUI invocation so users only need to
#     pass the flags they want to add or override (e.g. --port 9000).
#
# Secrets priority:
#   1. vast.ai account/template env vars (e.g. HF_TOKEN=hf_xxx) — highest
#   2. /data/secrets/env.sh — fallback for vars not set by vast.ai
#      (only present when a volume is mounted at /data)
#
# For LoraManager's settings.json (a JSON file, not a single env var),
# we COPY from /data/secrets/ into the user config dir
# (~/.config/ComfyUI-LoRA-Manager/settings.json on Linux). Copying (not
# symlinking) keeps the volume source clean: Lora Manager auto-init writes
# (folder_paths, env-var-overridden civitai_api_key) land in the ephemeral
# copy, not back on the volume. Lora Manager's default behavior reads from
# the user config dir, so no LORA_MANAGER_PORTABLE override is needed.
#
# Files consumed (all optional — missing files are silently skipped,
# e.g. when no volume is mounted at /data):
#   /data/secrets/env.sh                       — sourced as shell env vars
#                                                 (e.g. export HF_TOKEN=...)
#   /data/secrets/lora-manager-settings.json   — copied to
#                                                 ~/.config/ComfyUI-LoRA-Manager/settings.json

# 1. Load env vars from volume, but let vast.ai env vars win.
#    Strategy: snapshot the known secret vars BEFORE sourcing env.sh,
#    source env.sh, then restore the snapshotted values (if any).
#    Add new secret var names to SECRETS_VARS as needed.
SECRETS_VARS="HF_TOKEN HUGGING_FACE_HUB_TOKEN CIVITAI_API_KEY CIVITAI_TOKEN"
# Save current values (empty if unset)
for _v in $SECRETS_VARS; do
    eval "_saved_$_v=\${$_v:-}"
done
if [ -f /data/secrets/env.sh ]; then
    echo "[entrypoint] Loading secrets from /data/secrets/env.sh"
    . /data/secrets/env.sh
fi
# Restore vast.ai-provided values (override anything env.sh set)
for _v in $SECRETS_VARS; do
    eval "_saved=\$_saved_$_v"
    if [ -n "$_saved" ]; then
        eval "export $_v=\$_saved"
    fi
done

# 2. Seed LoraManager settings.json.
#    Volume mode: copy the user's complete settings from /data/secrets/
#    (takes priority, user manages their own example_images_path there).
#    No-volume mode: ensure example_images_path defaults to the
#    /opt/comfyui/examples directory created at build time, so LoraManager
#    picks it up without manual UI configuration. setdefault preserves any
#    value the user set via the LoraManager UI on a previous run (container
#    restart, not recreate).
LORA_MANAGER_SRC="/data/secrets/lora-manager-settings.json"
LORA_MANAGER_DST_DIR="${HOME}/.config/ComfyUI-LoRA-Manager"
LORA_MANAGER_DST="${LORA_MANAGER_DST_DIR}/settings.json"
LORA_MANAGER_DEFAULT_EXAMPLES="/opt/comfyui/examples"
if [ -f "$LORA_MANAGER_SRC" ]; then
    echo "[entrypoint] Seeding LoraManager settings from /data/secrets/"
    mkdir -p "$LORA_MANAGER_DST_DIR"
    cp -f "$LORA_MANAGER_SRC" "$LORA_MANAGER_DST"
else
    echo "[entrypoint] Ensuring LoraManager example_images_path default"
    mkdir -p "$LORA_MANAGER_DST_DIR"
    LM_DST="$LORA_MANAGER_DST" LM_EXAMPLES="$LORA_MANAGER_DEFAULT_EXAMPLES" python3 -c '
import json, os
path = os.environ["LM_DST"]
default = os.environ["LM_EXAMPLES"]
data = {}
if os.path.isfile(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}
if not data.get("example_images_path"):
    data["example_images_path"] = default
with open(path, "w") as f:
    json.dump(data, f, indent=2)
'
fi

# 3. Build the command to run.
#    The default ComfyUI invocation is ALWAYS used as the base command,
#    and any user-provided args ($@) are APPENDED as extra parameters.
#    This lets users pass just the flags they want to tweak
#    (e.g. --port 9000) without rewriting the whole command.
#    ComfyUI's argparse takes the last value for repeated options, so
#    overriding --port etc. by passing it again works as expected.
#    To run an arbitrary command (e.g. a shell) instead of ComfyUI,
#    bypass the wrapper with `docker run --entrypoint <cmd> ...`.
#    We then exec nvidia_entrypoint.sh — the base image's original
#    ENTRYPOINT — which sets up the CUDA env (PATH, LD_LIBRARY_PATH, etc.)
#    before exec'ing the command. This preserves GPU support while
#    guaranteeing secrets are loaded regardless of whether vast.ai set args.
set -- python3 main.py --listen 0.0.0.0 --port "${COMFYUI_PORT}" $([ "${COMFYUI_CPU}" = "1" ] && echo --cpu) "$@"
# Full path required: nvidia_entrypoint.sh lives in /opt/nvidia/ which is
# NOT in PATH (only /opt/nvidia/bin is, for nvidia-smi).
exec /opt/nvidia/nvidia_entrypoint.sh "$@"
