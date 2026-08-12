# Preset Model Installer Design

## Goal

Provide a `comfy-models` command in the Vast.ai image that installs all models
declared in a YAML preset into the correct ComfyUI model directories.

## Scope

- The command is installed only in the Vast.ai custom image as
  `/usr/local/bin/comfy-models`.
- A preset is supplied as a positional YAML file path. Built-in presets are
  copied from this repository's `presets/` directory to
  `/opt/comfyui/presets/` in the image, but any readable YAML path is valid.
- The model root defaults to `/opt/comfyui/models` and can be overridden with
  `--models-dir PATH`. No model-path environment variable is introduced.
- The command uses the existing `hf` and `civitai` executables. Authentication
  comes only from the already-supported `HF_TOKEN`,
  `HUGGING_FACE_HUB_TOKEN`, `CIVITAI_API_KEY`, and `CIVITAI_TOKEN` variables.

The first built-in preset is `presets/krea2-rtx3060.yaml`. It installs the
Krea 2 int8 diffusion model, Qwen text encoder, and Qwen VAE from
`Comfy-Org/Krea-2`.

## Preset schema

```yaml
version: 1
name: krea2-rtx3060

models:
  - name: krea2-turbo-int8-convrot
    type: diffusion_model
    source:
      provider: huggingface
      repo_id: Comfy-Org/Krea-2
      filename: diffusion_models/krea2_turbo_int8_convrot.safetensors
```

Required top-level fields are `version`, `name`, and `models`. `version` must
be integer `1`; `name` must be a non-empty string; `models` must be a non-empty
list.

Every model must supply a non-empty `name`, a supported `type`, and one
provider-specific `source` object. The supported types and destination folders
are:

| Type | Destination below `--models-dir` |
| --- | --- |
| `diffusion_model` | `diffusion_models/` |
| `text_encoder` | `text_encoders/` |
| `vae` | `vae/` |
| `checkpoint` | `checkpoints/` |
| `lora` | `loras/` |
| `controlnet` | `controlnet/` |
| `upscale_model` | `upscale_models/` |

For `provider: huggingface`, `source.repo_id` and `source.filename` are
required. `source.revision` is optional; omitting it downloads the repository's
default revision, while a commit SHA or tag allows a user to pin a version.

For `provider: civitai`, `source.model_version_id` is required. Civitai's
`--layout comfyui` and `--root <ComfyUI root>` determine the final model
subdirectory from the model-version metadata. The preset `type` is validated
but does not override Civitai's layout choice.

## Command interface and data flow

```text
comfy-models install [--models-dir PATH] [--dry-run] [--force] PRESET.yaml
       │
       ├─ parse and validate YAML
       ├─ map each Hugging Face type to a ComfyUI destination folder
       ├─ run hf download <repo_id> <filename> --local-dir <staging directory>
       ├─ move the staged file to the mapped destination folder
       └─ run civitai download <model_version_id> --layout comfyui
                            --root <models-dir parent>
```

`--dry-run` validates the preset and prints each planned provider command
without downloading. By default an existing destination file is skipped;
`--force` runs the provider command again. The command creates missing
destination directories only after the preset has passed validation.

For Hugging Face downloads, the installer passes a per-run staging directory
under `<models-dir>/.comfy-models-staging/` to `--local-dir`. Hugging Face
preserves a source filename's relative path, so the installer then moves the
staged source file to the mapped destination folder using its basename. This
prevents a source such as `diffusion_models/model.safetensors` from creating
`diffusion_models/diffusion_models/model.safetensors`, and keeps Hugging
Face's `.cache/huggingface/` metadata out of the ComfyUI model folders.

The Civitai `--root` value is the parent of the selected models directory when
that directory is named `models`; otherwise Civitai installation is rejected
with an actionable message because its `comfyui` layout expects a ComfyUI root.
This keeps the Civitai command aligned with its documented layout semantics.

## Failure behavior

- Invalid YAML, unsupported schema version, missing fields, unsupported model
  types, unknown providers, and path traversal in a Hugging Face filename fail
  before any provider command runs.
- A missing `hf` or `civitai` executable reports which image variant is
  required and exits non-zero.
- Provider failures stop the install at that model, preserve files already
  downloaded by previous models, remove the current run's staging directory,
  and print the failed model name and command.
- Tokens are never accepted as command-line arguments or written to logs.

## Krea 2 preset

`presets/krea2-rtx3060.yaml` contains these Hugging Face entries:

| Type | Repository path |
| --- | --- |
| `diffusion_model` | `diffusion_models/krea2_turbo_int8_convrot.safetensors` |
| `text_encoder` | `text_encoders/qwen3vl_4b_bf16.safetensors` |
| `vae` | `vae/qwen_image_vae.safetensors` |

All three use `Comfy-Org/Krea-2` and intentionally omit `revision`, so the
preset tracks the repository's default revision.

## Verification plan

Python unit tests will cover schema validation, type-to-directory mapping,
argument construction, dry-run output, skip behavior, and safe rejection of
path traversal. Tests will replace external process execution with a fake
runner, so no real model download or token is needed. A Docker build check will
confirm the Vast.ai image copies the executable and bundled preset to their
intended locations.
