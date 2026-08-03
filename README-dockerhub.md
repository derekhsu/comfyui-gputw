# comfyui-gputw

Container image for [ComfyUI](https://github.com/comfyanonymous/ComfyUI), optimized for the **gpuai** GPU service.

**Platform: linux/amd64 only.**

## Available tags

| Tag | Description |
| --- | --- |
| `custom-v0.30.0-cu128-pt2.11.0` | **Production** — pinned ComfyUI v0.30.0 + CUDA 12.8 + PyTorch 2.11.0, with 26 custom nodes (MiniMax H3 native support) |
| `custom-latest` | Rolling tag pointing to the newest custom build |
| `v0.30.0-cu128-pt2.11.0` | Base image only (no custom nodes) |
| `latest` | Rolling tag for base image |

**For production, use the pinned `custom-<version>` tag.** Use `custom-latest` for ad-hoc testing.

## Quick start on gpuai

In the gpuai deploy form, set:

- **Image**: `derekhsu/comfyui-gputw:custom-v0.30.0-cu128-pt2.11.0`
- **Port**: `8080`

The container listens on `0.0.0.0:8080`. No volume mounts needed — gpuai auto-mounts `/vault` for persistent storage.

## Models

Models live under `/vault/models` (user-managed on the vault). The custom image ships an `extra_model_paths.yaml` that wires these subdirectories into ComfyUI's model scanner:

```
/vault/models/checkpoints/
/vault/models/vae/
/vault/models/diffusion_models/
/vault/models/text_encoders/
/vault/models/loras/
/vault/models/controlnet/
... (and more)
```

Just drop model files into the matching subdirectory — no image rebuild needed.

## Secrets

ComfyUI and custom nodes need API keys (HuggingFace, CivitAI). Two ways to provide them, **gpuai env vars take priority**:

1. **gpuai deploy-form env vars** (e.g. `HF_TOKEN=hf_xxx`) — for ad-hoc deployments
2. **`/vault/secrets/` files** — persistent fallback

| File in `/vault/secrets/` | Purpose | Example |
| --- | --- | --- |
| `env.sh` | Shell env vars (fallback) | `export HF_TOKEN=hf_xxxxxxxx` |
| `lora-manager-settings.json` | LoraManager settings (CivitAI API key) | See [example](https://github.com/willmiao/ComfyUI-Lora-Manager/blob/main/settings.json.example) |

All files are optional — missing files are silently skipped.

## Custom nodes included

The custom image includes 26 popular custom nodes (ComfyUI-Manager, Impact-Pack, VideoHelperSuite, Lora-Manager, etc.). See the full list at the [GitHub repo](https://github.com/derekhsu/comfyui-gputw/blob/main/custom-nodes.txt).

## Local testing

```bash
# With GPU
docker run --gpus all -p 8080:8080 derekhsu/comfyui-gputw:custom-latest

# CPU-only smoke test (very slow, not for inference)
docker run -e COMFYUI_CPU=1 -p 8080:8080 derekhsu/comfyui-gputw:custom-latest
```

UI at <http://localhost:8080>.

## Source & issues

- **GitHub**: https://github.com/derekhsu/comfyui-gputw
- **ComfyUI**: https://github.com/comfyanonymous/ComfyUI (GPL-3.0)
