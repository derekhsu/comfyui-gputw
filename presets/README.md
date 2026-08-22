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
with the int8-quantized Qwen3VL 4B text encoder and the native Qwen image VAE.

- `diffusion_model` — `Comfy-Org/Krea-2` → `krea2_turbo_int8_convrot.safetensors`
- `text_encoder`    — `Merserk/qwen3vl-4b-int8-convrot` → `qwen3vl_4b_int8_convrot.safetensors`
- `vae`             — `Comfy-Org/Krea-2` → `qwen_image_vae.safetensors`

### krea2-rtx3060-wanvae.yaml

Same Krea-2 Turbo stack as above, but swaps the VAE for the Wan 2.1 VAE
from the Comfy-Org repackaged split-files bundle. Use this when you prefer
the Wan 2.1 VAE's characteristics over the native Qwen image VAE.

- `diffusion_model` — `Comfy-Org/Krea-2` → `krea2_turbo_int8_convrot.safetensors`
- `text_encoder`    — `Merserk/qwen3vl-4b-int8-convrot` → `qwen3vl_4b_int8_convrot.safetensors`
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

### Civitai versions with multiple files

A Civitai version can ship several files (e.g. fp8/fp16/gguf of the same
model). Without a selector, `comfy-models` downloads the version's
**primary file** only. To pick a specific file, add a `file` field to the
civitai source — it accepts either a **filename substring** (matched
case-insensitively, must be unique) or a numeric **file id**:

```yaml
- name: example
  type: lora
  source:
    provider: civitai
    model_version_id: 3066243
    file: 2982648          # numeric file id — use when files share a name
    # file: ".gguf"        # or a unique filename substring
```

Civitai's web UI does not show file ids. Look them up via the public API:

```bash
curl -s https://civitai.com/api/v1/model-versions/<version_id> \
  | python3 -c "import json,sys; [print(f['id'], f['name'], f.get('metadata',{}).get('format'), f.get('metadata',{}).get('fp'), f['primary']) for f in json.load(sys.stdin)['files']]"
```

When a version has multiple files with the same name (common for
safetensors builds at different precision), use the numeric file id — a
filename substring would be ambiguous and the CLI will refuse.

### Civitai preview images and metadata sidecars

After each Civitai download, `comfy-models` automatically fetches the
version metadata via `civitai mv get <version_id> --json` and writes two
sidecar files next to the model for [ComfyUI-Lora-Manager](https://github.com/willmiao/ComfyUI-Lora-Manager):

- **Preview image** — `<basename>.<ext>` (e.g. `my_lora.png`), downloaded
  from the version's first image. LoRA Manager auto-detects sidecar images
  named `<basename>.[png|jpg|jpeg|mp4]`.
- **Metadata JSON** — `<basename>.metadata.json`, containing the Civitai
  API response plus the fields LoRA Manager reads (`model_name`,
  `base_model`, `trainedWords`, `tags`, `modelDescription`, `preview_url`,
  `from_civitai`, `civitai`, etc.).

This means LoRA Manager shows the preview thumbnail, trigger words, tags,
and description without needing to fetch anything itself. Pass
`--no-sidecar` to skip sidecar generation:

```bash
comfy-models install <preset>.yaml --no-sidecar
```

Sidecar failures (metadata fetch error, image download error) are
non-fatal — the model itself is already downloaded, so warnings go to
stderr and the install continues.

### dark-beast-30-krea2-int8.yaml

Dark Beast 30 diffusion model for Krea-2, int8-quantized. Single-model preset;
uses `file: 3053854` to select the int8 file from a multi-file Civitai version.

- `diffusion_model` — Civitai version `3173268` (file `3053854`)

Requires `CIVITAI_API_KEY` / `CIVITAI_TOKEN`.

### flux2-klein-f2k.yaml

Flux-2 Klein 9B supporting components for Goon's F2K I2I Edit + SeedVR2
workflow. Does **not** include the diffusion model itself (download separately
from Civitai version `3063794` or mirror). For SeedVR2 models, use
`seedvr2-3b-q4km.yaml` alongside this preset.

- `text_encoder`    — `Comfy-Org/vae-text-encorder-for-flux-klein-9b` → `split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors`
- `vae`             — `Comfy-Org/vae-text-encorder-for-flux-klein-9b` → `split_files/vae/flux2-vae.safetensors`
- `diffusion_model` — `cmeka/SeedVR2-GGUF` → `seedvr2_ema_3b-Q4_K_M.gguf`
- `vae`             — `cmeka/SeedVR2-GGUF` → `ema_vae_fp16.safetensors`

All files are public HuggingFace repos; no `HF_TOKEN` required.

### moody-cutie-mix-krea2-v40-int8.yaml

Moody Cutie Mix v40 Krea-2 diffusion model, int8-quantized. Uses `file:
3092829` to select the int8 file.

- `diffusion_model` — Civitai version `3211049` (file `3092829`)

Requires `CIVITAI_API_KEY` / `CIVITAI_TOKEN`.

### moody-krea2-mix-v70-int8.yaml

Moody Krea2 Mix v70 diffusion model, int8-quantized. Uses `file: 3090690` to
select the int8 file.

- `diffusion_model` — Civitai version `3209007` (file `3090690`)

Requires `CIVITAI_API_KEY` / `CIVITAI_TOKEN`.

### nsfw-loras-krea2.yaml

Seven NSFW LoRAs for Krea-2 from Civitai: anatomical sliders (pubic hair,
labia, breast size), quality-enhancement LoRAs, and style LoRAs. All
download the primary file (no `file` selector needed).

- `lora` — Civitai versions: `3147117`, `3220691`, `3136749`, `3170393`, `3131773`, `3116175`, `3111211`

Requires `CIVITAI_API_KEY` / `CIVITAI_TOKEN`.

### pornmaster-krea2-v25turbo-int8.yaml

Pornmaster Krea2 v25 Turbo diffusion model, int8-quantized. Uses `file:
3051927` to select the int8 file.

- `diffusion_model` — Civitai version `3171380` (file `3051927`)

Requires `CIVITAI_API_KEY` / `CIVITAI_TOKEN`.

### redcraft-30-krea2-int8.yaml

RedCraft RedMix 30 Krea-2 diffusion model, int8-quantized. Uses `file:
3019607` to select the int8 file.

- `diffusion_model` — Civitai version `3139241` (file `3019607`)

Requires `CIVITAI_API_KEY` / `CIVITAI_TOKEN`.

### seedvr2-3b-q4km.yaml

SeedVR2 video super-resolution/restoration stack using the 3B model in
GGUF Q4_K_M quantization (2 GB), paired with the fp16 VAE. The Q4_K_M
quantization fits comfortably in ~8 GB VRAM. Models are placed in
`models/SEEDVR2/` as expected by the `ComfyUI-SeedVR2_VideoUpscaler`
custom node (already included in `custom-nodes.txt`).

- `seedvr2` — `cmeka/SeedVR2-GGUF` → `seedvr2_ema_3b-Q4_K_M.gguf` (2 GB)
- `seedvr2` — `numz/SeedVR2_comfyUI` → `ema_vae_fp16.safetensors` (501 MB)

Both files are public HuggingFace repos, so no `HF_TOKEN` is required for
download. Other GGUF quantizations (Q3_K_M 1.55 GB, Q5_K_M 2.41 GB,
Q6_K 2.85 GB, Q8_0 3.66 GB) and 7B variants are available in
`cmeka/SeedVR2-GGUF` — copy this preset and swap the filename (and preset
`name`) to switch.
