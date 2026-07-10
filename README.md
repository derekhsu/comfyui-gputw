# comfyui-gputw

Container image for [ComfyUI](https://github.com/comfyanonymous/ComfyUI), built to run under the gputw GPU service.

**Platform: linux/amd64 only.** The base image `nvidia/cuda:...` does not ship arm64 manifests, and there is no use case for running this image on anything but a Linux x86_64 GPU server.

## Build

Always go through `docker buildx` and pin the platform.

```bash
# one-time: create a buildx builder if you don't already have one
docker buildx create --name comfyui-builder --use

# build for the production GPU server
docker buildx build --platform=linux/amd64 -t comfyui-gputw:local --load .
```

The Dockerfile also pins `FROM --platform=linux/amd64` as a safety net, but the buildx command is the source of truth.

Default ComfyUI version is `v0.27.0`. To pin a different release:

```bash
docker buildx build --platform=linux/amd64 \
    --build-arg COMFYUI_VERSION=v0.27.0 \
    -t comfyui-gputw:v0.27.0 --load .
```

See [ComfyUI releases](https://github.com/comfyanonymous/ComfyUI/releases) for available tags.

## Push to a registry

```bash
# Docker Hub
docker buildx build --platform=linux/amd64 \
    --build-arg COMFYUI_VERSION=v0.27.0 \
    -t docker.io/<your-user>/comfyui-gputw:v0.27.0 --push .

# GitHub Container Registry
docker buildx build --platform=linux/amd64 \
    --build-arg COMFYUI_VERSION=v0.27.0 \
    -t ghcr.io/<your-user>/comfyui-gputw:v0.27.0 --push .
```

## Run

### Production: gpuai platform

The image is built for the **gpuai** GPU service. gpuai supports:

- **Environment variables**: `KEY=VALUE` per line in the deploy form
- **Startup arguments**: per-line args that replace the image CMD (ENTRYPOINT preserved)
- **Volumes**: NOT supported — only `/vault` (persistent storage root) is auto-mounted

Models live under `/vault/models` (user-managed subdirectory). The custom
image (`derekhsu/comfyui-gputw:custom-<tag>`) ships an
`extra_model_paths.yaml` that wires `/vault/models` into ComfyUI's model
scanner, so checkpoints / VAEs / diffusion models / text encoders placed
on the vault are visible in the UI without copying them into the image.

The container listens on `0.0.0.0:8080` so the gpuai orchestrator can reach it.

### Secrets (API keys, tokens)

ComfyUI and custom nodes need secrets (HuggingFace token, CivitAI API key).
Since the image is on public Docker Hub, secrets cannot be baked in. Two ways
to provide them, **gpuai env vars take priority**:

1. **gpuai deploy-form env vars** (e.g. `HF_TOKEN=hf_xxx`) — for ad-hoc deployments
2. **`/vault/secrets/` files** — persistent fallback, managed on the vault

The custom image's `entrypoint-wrapper.sh` is set as the image **ENTRYPOINT** (not CMD), so it always runs — even when gpuai replaces CMD with startup arguments. It sources `/vault/secrets/env.sh` but restores any secret vars that gpuai already set, so deploy-form env vars always win. After loading secrets, it exec's `nvidia_entrypoint.sh` (the base image's original entrypoint, which sets up the CUDA env) with either the default ComfyUI command or the gpuai-provided startup args. Create these files directly on the vault (they never enter git or the image):

| File in `/vault/secrets/` | Purpose | Example |
| --- | --- | --- |
| `env.sh` | Shell env vars (fallback if not set via gpuai) | `export HF_TOKEN=hf_xxxxxxxx` |
| `lora-manager-settings.json` | LoraManager settings (CivitAI API key, JSON) | See [settings.json.example](https://github.com/willmiao/ComfyUI-Lora-Manager/blob/main/settings.json.example) |

All files are optional — missing files are silently skipped so the image boots fine without them.

### Local docker run (dev / smoke test only)

The commands below are for local testing only — they do **not** reflect how
the image runs on gpuai (gpuai accepts no `-e` / `-v` / argument overrides).

Production (with GPU):

```bash
docker run --gpus all -p 8080:8080 comfyui-gputw:local
```

UI is at <http://localhost:8080>.

### Override the port at runtime (local only)

```bash
docker run --gpus all -e COMFYUI_PORT=9090 -p 9090:9090 comfyui-gputw:local
```

### Local CPU smoke test (no GPU)

For a no-GPU x86_64 host (e.g. a Linux dev box without an NVIDIA driver) where you just want to confirm the image starts, port 8080 is listening, and the UI serves a page — set `COMFYUI_CPU=1`. ComfyUI will boot in CPU mode (very slow; **not for actual inference**):

```bash
docker run -e COMFYUI_CPU=1 -p 8080:8080 comfyui-gputw:local
```

## Layout

| Path | Purpose |
| --- | --- |
| `/opt/comfyui` | ComfyUI source tree |
| `/opt/comfyui/models` | ComfyUI's built-in model dir (empty; real models come from `/vault/models` via `extra_model_paths.yaml` in the custom image) |
| `/opt/comfyui/output` | Generated images — persistent only when mounted; on gpuai this is **TBD** |
| `/opt/comfyui/input` | Optional input directory |
| `/vault/models` | gpuai persistent storage root (`/vault`) + user-managed `models/` — checkpoints, VAEs, diffusion models, text encoders, LoRAs, etc. |

## Host requirements

- **Production:** NVIDIA GPU with a driver that supports CUDA 12.8, plus [`nvidia-container-toolkit`](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) for `--gpus all`
- **Local CPU smoke test:** no GPU or driver required (linux/amd64 only)

## Build args

| Arg | Default | Description |
| --- | --- | --- |
| `COMFYUI_VERSION` | `v0.27.0` | ComfyUI release tag; downloaded as a zip |
| `PYTORCH_CUDA_TAG` | `cu128` | PyTorch wheel index suffix (e.g., `cu118`, `cu126`, `cu128`); the `nvidia/cuda` base image's CUDA version must be ≥ the one implied by this tag |
| `COMFYUI_PORT` | `8080` | Sets the default listening port baked into the image. On gpuai this is fixed at build time (no runtime override). For local `docker run` you can still override via `-e COMFYUI_PORT=9090`. |
| `COMFYUI_CPU` | `0` | When set to `1`, ComfyUI is launched with `--cpu` so the image can boot on a host without a GPU. On gpuai this is fixed at build time. For local `docker run` you can override via `-e COMFYUI_CPU=1`. |

## License

This Dockerfile is provided as-is. ComfyUI itself is licensed under GPL-3.0.

## CI

`.github/workflows/build.yml` builds and pushes two images to Docker Hub:

1. **Base image** (`Dockerfile`) — ComfyUI core + PyTorch. Tagged `derekhsu/comfyui-gputw:<final_tag>`.
2. **Custom image** (`Dockerfile.custom`) — layers custom nodes + `extra_model_paths.yaml` on top of the base. Tagged `derekhsu/comfyui-gputw:custom-<final_tag>`. Runs only after the base job succeeds.

Triggers:

- **Tag push** (`v*`): e.g. `git tag v0.27.0 && git push --tags` → base `:v0.27.0-cu128-pt2.11.0`, custom `:custom-v0.27.0-cu128-pt2.11.0` (the `pt*` suffix is read from the actually-installed torch at build time)
- **Manual dispatch**: Actions tab → Run workflow, with optional `comfyui_version`, `pytorch_cuda_tag`, and `image_tag` inputs. Leave `image_tag` empty for auto-generated version tags; set it to `dev` for a floating dev tag.

Base image tags follow the format `v<comfyui>-<cuda_tag>-pt<torch_version>`, e.g. `v0.27.0-cu128-pt2.11.0`. Custom image tags are `custom-` + the base tag. This lets gpuai pin to a specific ComfyUI + CUDA + PyTorch combination.

### Adding custom nodes

Edit `custom-nodes.txt` (one node per line, format `<git_url>,<ref>` where `ref` is branch/tag/SHA or empty for default branch), commit, and trigger the workflow. The base image is not rebuilt unless its own inputs change.

### Required secrets

Set these in the repo's `Settings → Secrets and variables → Actions`:

| Secret | Value |
| --- | --- |
| `DOCKERHUB_USERNAME` | Your Docker Hub username (`derekhsu`) |
| `DOCKERHUB_TOKEN` | A Docker Hub access token with Read, Write, Delete permission ([generate here](https://hub.docker.com/settings/security)) |