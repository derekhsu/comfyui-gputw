# AGENTS.md

Project conventions for AI agents working on comfyui-gputw.

## Project purpose

Container image for [ComfyUI](https://github.com/comfyanonymous/ComfyUI) that runs on the **gpuai** GPU service. Two-layer image design:

- **Base** (`Dockerfile`) — ComfyUI core + PyTorch cu128. ~6.9 GB compressed. Generic, no gpuai-specific assumptions.
- **Custom** (`Dockerfile.custom`) — layers custom nodes (`custom-nodes.txt`) + `extra_model_paths.yaml` on top of the base. This is where gpuai-deployment-specific config lives.

## Critical: gpuai deployment constraints

gpuai now supports **runtime env vars** and **startup arguments** in the deploy form (see https://docs.gputw.ai/templates). Specifically:

- **Environment variables**: `KEY=VALUE` per line in the deploy form, injected as container env vars
- **Startup arguments**: per-line args that **replace the image CMD** (ENTRYPOINT is preserved)
- **Volumes**: still NOT supported — the only platform-provided mount is `/vault` (persistent storage root, auto-mounted)

Implications for design decisions:

- Runtime env vars (`COMFYUI_PORT`, `COMFYUI_CPU`, `HF_TOKEN`, etc.) CAN now be set via the gpuai deploy form. But for reproducibility, secrets should still default to `/vault/secrets/` so the same image works without manual deploy-form entry.
- Model paths must be wired via `extra_model_paths.yaml` baked into the custom image, not via `-v` mounts.
- Any config file ComfyUI needs at runtime must be COPY'd into the image, not mounted.
- **Secrets (API keys, tokens)**: see "Secrets" section below.
- Output persistence (`/opt/comfyui/output`) on gpuai is **TBD** — do not assume it is persistent.

## Secrets (API keys, tokens)

ComfyUI and custom nodes need secrets (HuggingFace token, CivitAI API key). Since the image is on public Docker Hub, secrets cannot be baked in. Two ways to provide them, **gpuai env vars take priority**:

1. **gpuai deploy-form env vars** (e.g. `HF_TOKEN=hf_xxx`) — highest priority, use for ad-hoc/temporary deployments
2. **`/vault/secrets/` files** — fallback for persistent deployments, managed by the user on the vault

The custom image's `entrypoint-wrapper.sh` is set as the image **ENTRYPOINT** (not CMD) so it always runs, even when gpuai replaces CMD with startup arguments. It sources `/vault/secrets/env.sh` but restores any secret vars that gpuai already set, so deploy-form env vars always win. After loading secrets, it exec's `nvidia_entrypoint.sh` (the base image's original entrypoint, which sets up the CUDA env) with either the default ComfyUI command or the gpuai-provided startup args.

| Source | Purpose | How it's loaded |
| --- | --- | --- |
| gpuai deploy-form env vars | `HF_TOKEN`, `CIVITAI_API_KEY`, etc. | injected by gpuai at container start |
| `/vault/secrets/env.sh` | Shell env vars (fallback) | sourced by wrapper script (does not override gpuai-set vars) |
| `/vault/secrets/lora-manager-settings.json` | LoraManager settings (JSON, contains `civitai_api_key`) | symlinked into `custom_nodes/ComfyUI-Lora-Manager/settings.json` |

All vault files are optional — missing files are silently skipped so the image boots fine without them. The user creates and manages these files directly on the vault; they never enter git or the image.

Secret var names currently tracked for priority handling (in `entrypoint-wrapper.sh`): `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`, `CIVITAI_API_KEY`. Add new ones to `SECRETS_VARS` in the wrapper script as needed.

## Image architecture

```
derekhsu/comfyui-gputw:<final_tag>              ← base (Dockerfile)
derekhsu/comfyui-gputw:custom-<final_tag>       ← custom (Dockerfile.custom, FROM base)
```

`<final_tag>` is computed in CI:

- Manual dispatch with `image_tag` input → that value (e.g. `dev`)
- Tag push (`v*`) → `v<comfyui>-<cuda>-pt<torch>` (torch version read from the built image)

Custom tag is always `custom-` + base tag. The two are always built in the same workflow run and are version-aligned.

## CI

`.github/workflows/build.yml` — two jobs:

1. `build` — builds base, detects torch version, tags, exports `final_tag`
2. `build-custom` — `needs: build`, builds custom image from the base tag

Both use GHA cache with separate scopes (`build-<ref>` and `build-custom-<ref>`) so custom rebuilds don't evict base layers. Cache is `mode=min` to stay within GHA's 10GB/repo limit.

Triggers: tag push (`v*`) and manual dispatch. Push to `main` does **not** auto-trigger — dispatch manually after pushing.

## Key files

| File | Purpose |
| --- | --- |
| `Dockerfile` | Base image: nvidia/cuda + Python 3 + ComfyUI + PyTorch |
| `Dockerfile.custom` | Custom layer: clones `custom-nodes.txt`, copies `extra_model_paths.yaml` |
| `custom-nodes.txt` | One node per line: `<git_url>,<ref>` (ref = branch/tag/SHA, empty = default) |
| `extra_model_paths.yaml` | Maps `/vault/models` subdirs into ComfyUI's model scanner |
| `entrypoint-wrapper.sh` | Loads secrets from `/vault/secrets/` at startup, then execs ComfyUI |
| `.github/workflows/build.yml` | CI: build + build-custom jobs |

## Base image gotchas (learned the hard way)

- **No `/usr/bin/python` symlink.** The `nvidia/cuda:...-ubuntu22.04` base only ships `python3`. Always use `python3`, never `python`, in both Dockerfile and workflow steps.
- **`nvidia_entrypoint.sh` prints a CUDA banner to stdout** before exec'ing the command. When capturing command output (e.g. `docker run ... python3 -c ...`), use `--entrypoint python3` to bypass the entrypoint and get clean stdout.
- **apt lists and pip cache are already cleaned** in the Dockerfile (`PIP_NO_CACHE_DIR=1`, `--no-cache-dir`, `rm -rf /var/lib/apt/lists/*`). The 6.9GB image size is actual installed packages (PyTorch 2GB + ComfyUI deps 4.3GB), not cache. Don't waste time on cache-cleanup optimizations.

## Workflow for adding a custom node

1. Edit `custom-nodes.txt`, add a line: `https://github.com/<owner>/<repo>,<ref>`
2. Commit and push to `main`
3. Manually dispatch the workflow (push to main does not auto-trigger):
   ```
   gh workflow run build.yml --ref main -f comfyui_version=v0.27.0 -f pytorch_cuda_tag=cu128 -f image_tag=dev
   ```
4. Base job uses cache (~2min), custom job clones the new node (~2-4min depending on node deps)
5. Custom image appears at `derekhsu/comfyui-gputw:custom-dev`

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
- Don't add runtime `-v` volume mounts — gpuai still doesn't support them. Use `/vault` (auto-mounted) or bake config into the image.
- Don't bake secrets into the image (ENV or ARG) — the image is on public Docker Hub. Use `/vault/secrets/` or gpuai deploy-form env vars.
- Don't put gpuai-specific paths (`/vault/...`) in the base Dockerfile — keep base generic; gpuai config goes in `Dockerfile.custom`.
- Don't use `cache-to: type=gha,mode=max` — it grows unbounded and risks GHA cache eviction. Use `mode=min`.
- Don't use unscoped GHA cache (`type=gha` without `scope=`) — different triggers will collide.
