# AGENTS.md

Project conventions for AI agents working on comfyui-gputw.

## Project purpose

Container images for [ComfyUI](https://github.com/comfyanonymous/ComfyUI) that run on the **gpuai** and **Vast.ai** GPU services. The base image is platform-neutral; each platform has its own custom layer:

- **Base** (`Dockerfile`) — ComfyUI core + PyTorch cu128. ~6.9 GB compressed. Generic, with no platform-specific assumptions.
- **gpuai custom** (`Dockerfile.custom`) — layers custom nodes (`custom-nodes.txt`) + `extra_model_paths.yaml` on top of the base. Contains gpuai-specific `/vault` configuration.
- **Vast.ai custom** (`Dockerfile.vast`) — layers the same custom nodes and the Civitai CLI on top of the base. Contains Vast.ai-specific `/data` configuration.

## Critical: platform deployment constraints

### gpuai

gpuai supports **runtime env vars** and **startup arguments** in the deploy form (see https://docs.gputw.ai/templates). Specifically:

- **Environment variables**: `KEY=VALUE` per line in the deploy form, injected as container env vars
- **Startup arguments**: per-line args that **replace the image CMD** (ENTRYPOINT is preserved)
- **Volumes**: still NOT supported — the only platform-provided mount is `/vault` (persistent storage root, auto-mounted)

Implications for design decisions:

- Runtime env vars (`COMFYUI_PORT`, `COMFYUI_CPU`, `HF_TOKEN`, etc.) CAN now be set via the gpuai deploy form. But for reproducibility, secrets should still default to `/vault/secrets/` so the same image works without manual deploy-form entry.
- Model paths must be wired via `extra_model_paths.yaml` baked into the custom image, not via `-v` mounts.
- Any config file ComfyUI needs at runtime must be COPY'd into the image, not mounted.
- **Secrets (API keys, tokens)**: see "Secrets" section below.
- Output persistence (`/opt/comfyui/output`) on gpuai is **TBD** — do not assume it is persistent.

### Vast.ai

- Use the `vast-<base_tag>` image variant, not the gpuai `custom-<base_tag>` variant.
- Vast.ai storage volumes are local to one physical machine. The image therefore does not bake model paths into its configuration; download models at runtime with `hf download` or `civitai download`, or pass `--model-paths-config /path/to/config.yaml` through Vast.ai startup arguments when using a mounted volume.
- The Vast.ai custom image reads optional persistent secrets from `/data/secrets/`, the default volume mount path.
- Select Vast.ai's **docker ENTRYPOINT** launch mode. SSH and Jupyter launch modes replace the image entrypoint, so the wrapper cannot load secrets or assemble the default ComfyUI command.
- Environment variables configured in a Vast.ai account or template take priority over values in `/data/secrets/env.sh`.
- The Vast.ai image includes `comfy-models`, a YAML-preset installer for models. It defaults to `/opt/comfyui/models`; use `--models-dir` only when a different ComfyUI models directory is required. It uses only the existing Hugging Face and Civitai credential environment variables.

## Secrets (API keys, tokens)

ComfyUI and custom nodes need secrets (HuggingFace token, CivitAI API key). Since the images are on public Docker Hub, secrets cannot be baked in. Runtime environment variables always take priority over the corresponding optional secret file.

### gpuai

1. **gpuai deploy-form env vars** (e.g. `HF_TOKEN=hf_xxx`) — highest priority, use for ad-hoc/temporary deployments
2. **`/vault/secrets/` files** — fallback for persistent deployments, managed by the user on the vault

The custom image's `entrypoint-wrapper.sh` is set as the image **ENTRYPOINT** (not CMD) so it always runs, even when gpuai replaces CMD with startup arguments. It sources `/vault/secrets/env.sh` but restores any secret vars that gpuai already set, so deploy-form env vars always win. After loading secrets, it exec's `nvidia_entrypoint.sh` (the base image's original entrypoint, which sets up the CUDA env) with either the default ComfyUI command or the gpuai-provided startup args.

| Source | Purpose | How it's loaded |
| --- | --- | --- |
| gpuai deploy-form env vars | `HF_TOKEN`, `CIVITAI_API_KEY`, etc. | injected by gpuai at container start |
| `/vault/secrets/env.sh` | Shell env vars (fallback) | sourced by wrapper script (does not override gpuai-set vars) |
| `/vault/secrets/lora-manager-settings.json` | LoraManager settings (JSON: `civitai_api_key`, `example_images_path`, etc.) | copied to `~/.config/ComfyUI-LoRA-Manager/settings.json` by wrapper script |

All vault files are optional — missing files are silently skipped so the image boots fine without them. The user creates and manages these files directly on the vault; they never enter git or the image.

Secret var names currently tracked for priority handling (in `entrypoint-wrapper.sh`): `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`, `CIVITAI_API_KEY`. Add new ones to `SECRETS_VARS` in the wrapper script as needed.

### Vast.ai

1. **Vast.ai account/template environment variables** (for example, `HF_TOKEN=hf_xxx`) — highest priority
2. **`/data/secrets/` files** — fallback when a volume is mounted at `/data`

| Source | Purpose | How it's loaded |
| --- | --- | --- |
| Vast.ai account/template env vars | `HF_TOKEN`, `CIVITAI_API_KEY`, `CIVITAI_TOKEN`, etc. | injected at container start |
| `/data/secrets/env.sh` | Shell env vars (fallback) | sourced by `entrypoint-wrapper.vast.sh` without overriding platform-provided values |
| `/data/secrets/lora-manager-settings.json` | LoraManager settings JSON | copied to `~/.config/ComfyUI-LoRA-Manager/settings.json` by the wrapper |

All `/data/secrets/` files are optional. The Vast.ai wrapper tracks `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`, `CIVITAI_API_KEY`, and `CIVITAI_TOKEN` in `SECRETS_VARS`; add new secret variable names there when required.

## Image architecture

```
derekhsu/comfyui-gputw:<final_tag>              ← base (Dockerfile)
derekhsu/comfyui-gputw:custom-<final_tag>       ← custom (Dockerfile.custom, FROM base)
derekhsu/comfyui-gputw:vast-<base_tag>          ← Vast.ai custom (Dockerfile.vast, FROM base)
```

`<final_tag>` is computed in CI:

- Manual dispatch with `image_tag` input → that value (e.g. `dev`). No `latest` alias is created.
- Tag push (`v*`) or manual dispatch without `image_tag` → `v<comfyui>-<cuda>-pt<torch>` (torch version read from the built image, `+cuXXX` suffix stripped). Also tagged as `latest` (base) and `custom-latest` (custom).

Custom tag is always `custom-` + base tag. The two are always built in the same workflow run and are version-aligned.

The Vast.ai tag is always `vast-` + the explicitly selected published base tag. It is built separately, so it may be rebuilt independently from the base and gpuai custom image. `vast-latest` is updated only when the Vast.ai workflow is built from a versioned base tag without a custom suffix.

Tag format breakdown (`v0.27.0-cu128-pt2.6.0`):

| Segment | Meaning | Source |
| --- | --- | --- |
| `v0.27.0` | ComfyUI version | git tag or `comfyui_version` input |
| `cu128` | PyTorch CUDA wheel tag | `pytorch_cuda_tag` input |
| `pt2.6.0` | PyTorch version | `torch.__version__` read from the built image |

For production deployments, use the pinned `custom-<final_tag>` tag for reproducibility. Use `custom-latest` for ad-hoc/testing deployments that should track the newest release.

## CI

`.github/workflows/build.yml` — two jobs:

1. `build` — builds base, detects torch version, tags, exports `final_tag`
2. `build-custom` — `needs: build`, builds custom image from the base tag

Both use GHA cache with separate scopes (`build-<ref>` and `build-custom-<ref>`) so custom rebuilds don't evict base layers. Cache is `mode=min` to stay within GHA's 10GB/repo limit.

Triggers: tag push (`v*`) and manual dispatch. Push to `main` does **not** auto-trigger — dispatch manually after pushing.

`.github/workflows/build-vast.yml` — one manual-dispatch job that builds and publishes `vast-<base_tag>` from an already-published base image. It accepts `base_tag`, optional `civitai_cli_version`, and an optional tag suffix. Its GHA cache scope is separate from the base and gpuai custom builds.

## Key files

| File | Purpose |
| --- | --- |
| `Dockerfile` | Base image: nvidia/cuda + Python 3 + ComfyUI + PyTorch |
| `Dockerfile.custom` | Custom layer: clones `custom-nodes.txt`, copies `extra_model_paths.yaml` |
| `Dockerfile.vast` | Vast.ai custom layer: clones `custom-nodes.txt`, installs Civitai CLI, and uses the Vast.ai entrypoint wrapper |
| `custom-nodes.txt` | One node per line: `<git_url>,<ref>` (ref = branch/tag/SHA, empty = default) |
| `extra_model_paths.yaml` | Maps `/vault/models` subdirs into ComfyUI's model scanner |
| `entrypoint-wrapper.sh` | Loads secrets from `/vault/secrets/` at startup, then execs ComfyUI |
| `entrypoint-wrapper.vast.sh` | Loads secrets from `/data/secrets/` at startup, then execs ComfyUI for Vast.ai |
| `scripts/comfy_models.py` | Vast.ai-only `comfy-models` CLI: validates YAML presets and downloads models with the bundled `hf` and `civitai` CLIs |
| `presets/` | Built-in `comfy-models` YAML presets, copied to `/opt/comfyui/presets/` in the Vast.ai image |
| `.github/workflows/build.yml` | CI: base + gpuai custom image jobs |
| `.github/workflows/build-vast.yml` | CI: manually builds the Vast.ai custom image from a published base tag |

## Base image gotchas (learned the hard way)

- **No `/usr/bin/python` symlink.** The `nvidia/cuda:...-ubuntu22.04` base only ships `python3`. Always use `python3`, never `python`, in both Dockerfile and workflow steps.
- **`nvidia_entrypoint.sh` prints a CUDA banner to stdout** before exec'ing the command. When capturing command output (e.g. `docker run ... python3 -c ...`), use `--entrypoint python3` to bypass the entrypoint and get clean stdout.
- **apt lists and pip cache are already cleaned** in the Dockerfile (`PIP_NO_CACHE_DIR=1`, `--no-cache-dir`, `rm -rf /var/lib/apt/lists/*`). The 6.9GB image size is actual installed packages (PyTorch 2GB + ComfyUI deps 4.3GB), not cache. Don't waste time on cache-cleanup optimizations.

## Workflow for adding a custom node

1. Edit `custom-nodes.txt`, add a line: `https://github.com/<owner>/<repo>,<ref>`
2. Commit and push to `main`
3. Manually dispatch the workflow (push to main does not auto-trigger):
   ```
   gh workflow run build.yml --ref main -f comfyui_version=v0.31.0 -f pytorch_cuda_tag=cu128 -f image_tag=dev
   ```
4. Base job uses cache (~2min), gpuai custom job clones the new node (~2-4min depending on node deps)
5. gpuai custom image appears at `derekhsu/comfyui-gputw:custom-dev`
6. To publish the matching Vast.ai variant, then dispatch:
   ```bash
   gh workflow run build-vast.yml --ref main -f base_tag=dev
   ```
   The Vast.ai image appears at `derekhsu/comfyui-gputw:vast-dev`.

## Verification commands

```bash
# list recent runs
gh run list --limit 5

# view a specific run
gh run view <run_id>

# view failed step logs
gh run view <run_id> --log-failed

# inspect a pushed image's layers
docker manifest inspect derekhsu/comfyui-gputw:<tag> --verbose
```

## Things NOT to do

- Don't add `python` (without `3`) anywhere — use `python3`.
- Don't add runtime `-v` volume mounts to gpuai instructions — gpuai still doesn't support them. Use `/vault` (auto-mounted) or bake config into the gpuai custom image.
- Don't bake secrets into an image (ENV or ARG) — images are public on Docker Hub. Use the matching platform's runtime env vars or secret files: `/vault/secrets/` on gpuai and `/data/secrets/` on Vast.ai.
- Don't put gpuai-specific paths (`/vault/...`) or Vast.ai-specific paths (`/data/...`) in the base Dockerfile — keep base generic; platform config belongs in its matching custom Dockerfile and wrapper.
- Don't use `cache-to: type=gha,mode=max` — it grows unbounded and risks GHA cache eviction. Use `mode=min`.
- Don't use unscoped GHA cache (`type=gha` without `scope=`) — different triggers will collide.
