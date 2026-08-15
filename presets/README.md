# ComfyUI Model Presets

YAML presets for the `comfy-models` CLI (Vast.ai image only). Each preset
declares a set of models to download into ComfyUI's `models/` directory at
runtime. See `scripts/comfy_models.py` for the schema and CLI reference.

## Usage

```bash
# Preview the download plan (no transfer)
comfy-models install /opt/comfyui/presets/<preset>.yaml --dry-run

# Install to the default models dir (/opt/comfyui/models)
comfy-models install /opt/comfyui/presets/<preset>.yaml

# Install to a different models dir
comfy-models install /opt/comfyui/presets/<preset>.yaml --models-dir /data/comfyui/models

# Force redownload of files that already exist
comfy-models install /opt/comfyui/presets/<preset>.yaml --force
```

## Presets

### krea2-rtx3060.yaml

Krea-2 Turbo image generation stack tuned for a 12 GB GPU (e.g. RTX 3060).
Uses the int8-quantized diffusion model to fit within limited VRAM, paired
with the 4B Qwen3VL text encoder and the native Qwen image VAE.

- `diffusion_model` — `Comfy-Org/Krea-2` → `krea2_turbo_int8_convrot.safetensors`
- `text_encoder`    — `Comfy-Org/Krea-2` → `qwen3vl_4b_bf16.safetensors`
- `vae`             — `Comfy-Org/Krea-2` → `qwen_image_vae.safetensors`

### krea2-rtx3060-wanvae.yaml

Same Krea-2 Turbo stack as above, but swaps the VAE for the Wan 2.1 VAE
from the Comfy-Org repackaged split-files bundle. Use this when you prefer
the Wan 2.1 VAE's characteristics over the native Qwen image VAE.

- `diffusion_model` — `Comfy-Org/Krea-2` → `krea2_turbo_int8_convrot.safetensors`
- `text_encoder`    — `Comfy-Org/Krea-2` → `qwen3vl_4b_bf16.safetensors`
- `vae`             — `Comfy-Org/Wan_2.1_ComfyUI_repackaged` → `wan_2.1_vae.safetensors`

### krea2-lora-default.yaml

A default Krea 2 LoRA set: two detail-enhancement LoRAs from Civitai plus a
concept LoRA from a private HuggingFace repo. All target the Krea 2 base
model.

- `lora` — Civitai version `3097834` → "Skin Detail Slider - (Krea2 + ZIT)" (`skindetails_krea2_loraholic.safetensors`)
- `lora` — Civitai version `3068874` → "[KREA 2] Detail Slider" (`Detailer-KREA2.safetensors`)
- `lora` — HuggingFace `derekhsu/loras` → `concept/krea2/k2_bp_v2.0.safetensors`

Civitai downloads require `CIVITAI_API_KEY` (or `CIVITAI_TOKEN`) to be set
via Vast.ai env vars or `/data/secrets/env.sh`. The `civitai download`
command only accepts a version id; the model id is not needed for download.
The HuggingFace download requires `HF_TOKEN` with read access to
`derekhsu/loras`.
