# AGENTS.md

Project conventions for AI agents working on comfyui-gputw.

## Project purpose

Container image for [ComfyUI](https://github.com/comfyanonymous/ComfyUI) that runs on the **gpuai** GPU service. Two-layer image design:

- **Base** (`Dockerfile`) — ComfyUI core + PyTorch cu128. ~6.9 GB compressed. Generic, no gpuai-specific assumptions.
- **Custom** (`Dockerfile.custom`) — layers custom nodes (`custom-nodes.txt`) + `extra_model_paths.yaml` on top of the base. This is where gpuai-deployment-specific config lives.

## Critical: gpuai deployment constraints

**gpuai accepts NO runtime configuration from the user.** You cannot specify:

- Volumes (`-v`)
- Command arguments
- Environment variables (`-e`)

Everything must be baked into the image at build time. The only platform-provided mount is `/vault` (persistent storage root, auto-mounted). The user manages subdirectories under it (e.g. `/vault/models`).

Implications for design decisions:

- Runtime-overridable env vars (`COMFYUI_PORT`, `COMFYUI_CPU`) are **local dev only** — on gpuai they are fixed at build time. Do not design features that rely on runtime env overrides for production.
- Model paths must be wired via `extra_model_paths.yaml` baked into the custom image, not via `-v` mounts.
- Any config file ComfyUI needs at runtime must be COPY'd into the image, not mounted.
- Output persistence (`/opt/comfyui/output`) on gpuai is **TBD** — do not assume it is persistent.

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
- Don't add runtime `-v` / `-e` based features as if they work on gpuai — they don't.
- Don't put gpuai-specific paths (`/vault/...`) in the base Dockerfile — keep base generic; gpuai config goes in `Dockerfile.custom`.
- Don't use `cache-to: type=gha,mode=max` — it grows unbounded and risks GHA cache eviction. Use `mode=min`.
- Don't use unscoped GHA cache (`type=gha` without `scope=`) — different triggers will collide.
