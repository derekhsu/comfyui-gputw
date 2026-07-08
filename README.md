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

Production (with GPU):

```bash
docker run --gpus all -p 8080:8080 comfyui-gputw:local
```

UI is at <http://localhost:8080>.

### Override the port at runtime

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
| `/opt/comfyui/models` | Checkpoints / VAEs / LoRAs — **mount as a persistent volume** |
| `/opt/comfyui/output` | Generated images — **mount as a persistent volume** |
| `/opt/comfyui/input` | Optional input directory |

The container listens on `0.0.0.0:8080` so the gputw orchestrator can reach it.

## Host requirements

- **Production:** NVIDIA GPU with a driver that supports CUDA 12.8, plus [`nvidia-container-toolkit`](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) for `--gpus all`
- **Local CPU smoke test:** no GPU or driver required (linux/amd64 only)

## Build args

| Arg | Default | Description |
| --- | --- | --- |
| `COMFYUI_VERSION` | `v0.27.0` | ComfyUI release tag; downloaded as a zip |
| `PYTORCH_CUDA_TAG` | `cu128` | PyTorch wheel index suffix (e.g., `cu118`, `cu126`, `cu128`); the `nvidia/cuda` base image's CUDA version must be ≥ the one implied by this tag |
| `COMFYUI_PORT` | `8080` | Sets the default listening port baked into the image. Runtime can still override via `docker run -e COMFYUI_PORT=9090` (or in `gpuai` config) without rebuilding. |
| `COMFYUI_CPU` | `0` | When set to `1`, ComfyUI is launched with `--cpu` so the image can boot on a host without a GPU. Runtime can override via `docker run -e COMFYUI_CPU=1`. |

## License

This Dockerfile is provided as-is. ComfyUI itself is licensed under GPL-3.0.

## CI

`.github/workflows/build.yml` builds and pushes to Docker Hub on:

- **Tag push** (`v*`): e.g. `git tag v0.27.0 && git push --tags` → image `derekhsu/comfyui-gputw:v0.27.0-cu128-pt2.7.0` (the `pt*` suffix is read from the actually-installed torch at build time)
- **Manual dispatch**: Actions tab → Run workflow, with optional `comfyui_version` and `pytorch_cuda_tag` inputs

Image tags follow the format `v<comfyui>-<cuda_tag>-pt<torch_version>`, e.g. `v0.27.0-cu128-pt2.7.0`. This lets gputw pin to a specific ComfyUI + CUDA + PyTorch combination.

### Required secrets

Set these in the repo's `Settings → Secrets and variables → Actions`:

| Secret | Value |
| --- | --- |
| `DOCKERHUB_USERNAME` | Your Docker Hub username (`derekhsu`) |
| `DOCKERHUB_TOKEN` | A Docker Hub access token with Read, Write, Delete permission ([generate here](https://hub.docker.com/settings/security)) |