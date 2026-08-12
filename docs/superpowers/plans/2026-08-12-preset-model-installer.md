# Preset Model Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `comfy-models` command to the Vast.ai image that installs models declared in a YAML preset into their ComfyUI model directories.

**Architecture:** A Python CLI validates the whole YAML file before it changes the filesystem or invokes a provider. It calls the existing `hf` and `civitai` executables through an injected runner, so unit tests cover command construction without credentials or network access. Only `Dockerfile.vast` bundles the CLI and PyYAML.

**Tech Stack:** Python 3.10, PyYAML, `hf` CLI, Civitai CLI, Python `unittest`, Dockerfile.

---

## File structure

| File | Responsibility |
| --- | --- |
| `scripts/comfy_models.py` | Schema validation, destination mapping, provider command planning, installation, and `argparse` entry point. |
| `tests/test_comfy_models.py` | Unit tests using a fake command runner. |
| `presets/krea2-rtx3060.yaml` | Approved built-in Krea 2 RTX 3060 preset. |
| `Dockerfile.vast` | Installs PyYAML and bundles the command and presets. |
| `README.md` | Explains Vast.ai preset installation. |
| `AGENTS.md` | Records the new CLI and preset locations. |

### Task 1: Validate presets and build provider download plans

**Files:**

- Create: `scripts/comfy_models.py`
- Create: `tests/test_comfy_models.py`

- [ ] **Step 1: Write the failing validation and command-plan tests**

```python
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "comfy_models.py"
SPEC = importlib.util.spec_from_file_location("comfy_models", SCRIPT)
comfy_models = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comfy_models)

class ValidationTests(unittest.TestCase):
    def hf_preset(self, filename="nested/flux.safetensors"):
        return {
            "version": 1,
            "name": "example",
            "models": [{
                "name": "flux",
                "type": "diffusion_model",
                "source": {
                    "provider": "huggingface",
                    "repo_id": "org/repo",
                    "filename": filename,
                },
            }],
        }

    def test_hugging_face_model_maps_to_diffusion_models(self):
        model = comfy_models.validate_preset(self.hf_preset())[0]
        self.assertEqual(model.destination_directory, "diffusion_models")
        self.assertEqual(model.destination_filename, "flux.safetensors")

    def test_rejects_path_traversal_before_any_download(self):
        with self.assertRaisesRegex(comfy_models.PresetError, "path traversal"):
            comfy_models.validate_preset(self.hf_preset("../secret.safetensors"))

    def test_hugging_face_plan_uses_a_staging_directory(self):
        model = comfy_models.validate_preset(self.hf_preset())[0]
        with tempfile.TemporaryDirectory() as temporary:
            models_dir = Path(temporary) / "models"
            staging_dir = models_dir / ".comfy-models-staging" / "flux"
            plan = comfy_models.plan_download(model, models_dir, staging_dir)
            self.assertEqual(
                plan.command,
                ["hf", "download", "org/repo", "nested/flux.safetensors",
                 "--local-dir", str(staging_dir)],
            )
            self.assertEqual(
                plan.destination,
                models_dir / "diffusion_models" / "flux.safetensors",
            )

    def test_civitai_plan_uses_comfyui_layout(self):
        preset = {
            "version": 1,
            "name": "civitai-example",
            "models": [{
                "name": "style",
                "type": "lora",
                "source": {"provider": "civitai", "model_version_id": 123456},
            }],
        }
        model = comfy_models.validate_preset(preset)[0]
        plan = comfy_models.plan_download(model, Path("/opt/comfyui/models"), None)
        self.assertEqual(
            plan.command,
            ["civitai", "download", "123456", "--layout", "comfyui",
             "--root", "/opt/comfyui"],
        )
```

- [ ] **Step 2: Run the tests to verify they fail for the expected reason**

Run: `python3 -m unittest tests/test_comfy_models.py -v`

Expected: FAIL because `scripts/comfy_models.py` does not exist.

- [ ] **Step 3: Implement the validation and planning API**

Create `scripts/comfy_models.py` with these definitions:

```python
#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

TYPE_DIRECTORIES = {
    "diffusion_model": "diffusion_models",
    "text_encoder": "text_encoders",
    "vae": "vae",
    "checkpoint": "checkpoints",
    "lora": "loras",
    "controlnet": "controlnet",
    "upscale_model": "upscale_models",
}

class PresetError(ValueError):
    pass

@dataclass(frozen=True)
class Model:
    name: str
    provider: str
    destination_directory: str
    repo_id: str | None = None
    filename: str | None = None
    revision: str | None = None
    model_version_id: str | None = None

    @property
    def destination_filename(self):
        return PurePosixPath(self.filename).name if self.filename else None

@dataclass(frozen=True)
class DownloadPlan:
    command: list[str]
    destination: Path | None
    staged_source: Path | None
```

Implement `validate_preset(preset)` to reject a non-mapping, a version other than the integer `1`, a blank `name`, or an empty/non-list `models`. Implement `validate_model(raw, index)` to require a supported `type` and mapping `source`, then construct `Model` as follows:

```python
if provider == "huggingface":
    repo_id = require_non_empty(source.get("repo_id"), "huggingface repo_id")
    filename = require_non_empty(source.get("filename"), "huggingface filename")
    file_path = PurePosixPath(filename)
    if file_path.is_absolute() or ".." in file_path.parts:
        raise PresetError("huggingface filename contains path traversal")
    revision = source.get("revision")
    if revision is not None:
        revision = require_non_empty(revision, "huggingface revision")
    return Model(name, provider, TYPE_DIRECTORIES[model_type], repo_id, filename, revision)

if provider == "civitai":
    version_id = source.get("model_version_id")
    if not isinstance(version_id, (str, int)) or isinstance(version_id, bool) or not str(version_id):
        raise PresetError("civitai model_version_id must be a string or integer")
    return Model(name, provider, TYPE_DIRECTORIES[model_type], model_version_id=str(version_id))

raise PresetError(f"unsupported provider: {provider}")
```

Implement `plan_download(model, models_dir, staging_dir)` exactly as:

```python
def plan_download(model, models_dir, staging_dir):
    models_dir = Path(models_dir)
    if model.provider == "huggingface":
        command = ["hf", "download", model.repo_id, model.filename]
        if model.revision:
            command.extend(["--revision", model.revision])
        command.extend(["--local-dir", str(staging_dir)])
        return DownloadPlan(
            command,
            models_dir / model.destination_directory / model.destination_filename,
            Path(staging_dir) / PurePosixPath(model.filename),
        )
    if models_dir.name != "models":
        raise PresetError("Civitai requires --models-dir to end in 'models'")
    return DownloadPlan(
        ["civitai", "download", model.model_version_id, "--layout", "comfyui",
         "--root", str(models_dir.parent)],
        None,
        None,
    )
```

- [ ] **Step 4: Run the tests to verify the green state**

Run: `python3 -m unittest tests/test_comfy_models.py -v`

Expected: PASS for all four tests.

- [ ] **Step 5: Commit the validation and planning API**

```bash
git add scripts/comfy_models.py tests/test_comfy_models.py
git commit -m "feat: validate model presets"
```

### Task 2: Add YAML loading and safe installation behavior

**Files:**

- Modify: `scripts/comfy_models.py`
- Modify: `tests/test_comfy_models.py`

- [ ] **Step 1: Write failing tests for dry-run, skip, and staging moves**

```python
import io
from contextlib import redirect_stdout

class InstallTests(unittest.TestCase):
    def preset(self):
        return ValidationTests().hf_preset()

    def test_dry_run_prints_a_command_without_running_it(self):
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with redirect_stdout(output):
                comfy_models.install_models(
                    self.preset(), Path(temporary) / "models",
                    dry_run=True, force=False, runner=calls.append,
                )
        self.assertEqual(calls, [])
        self.assertIn("hf download org/repo nested/flux.safetensors", output.getvalue())

    def test_existing_hugging_face_file_is_skipped_without_force(self):
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            models_dir = Path(temporary) / "models"
            destination = models_dir / "diffusion_models" / "flux.safetensors"
            destination.parent.mkdir(parents=True)
            destination.touch()
            comfy_models.install_models(
                self.preset(), models_dir, dry_run=False, force=False, runner=calls.append,
            )
        self.assertEqual(calls, [])

    def test_hugging_face_download_moves_staged_file_to_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            models_dir = Path(temporary) / "models"
            def runner(command):
                staged_file = Path(command[-1]) / "nested" / "flux.safetensors"
                staged_file.parent.mkdir(parents=True)
                staged_file.write_text("model")
            comfy_models.install_models(
                self.preset(), models_dir, dry_run=False, force=False, runner=runner,
            )
            self.assertEqual(
                (models_dir / "diffusion_models" / "flux.safetensors").read_text(),
                "model",
            )
            self.assertFalse((models_dir / ".comfy-models-staging").exists())
```

- [ ] **Step 2: Run the tests to verify they fail for the expected reason**

Run: `python3 -m unittest tests/test_comfy_models.py -v`

Expected: FAIL because `install_models` does not exist.

- [ ] **Step 3: Implement YAML loading, provider execution, and installation**

Add these imports and functions to `scripts/comfy_models.py`:

```python
import shutil
import subprocess
import yaml

def load_preset(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except OSError as error:
        raise PresetError(f"cannot read preset: {error}") from error
    except yaml.YAMLError as error:
        raise PresetError(f"invalid YAML: {error}") from error

def run_command(command):
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as error:
        raise PresetError(f"required executable not found: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        raise PresetError(
            f"provider command failed ({error.returncode}): {' '.join(command)}"
        ) from error

def install_models(preset, models_dir, dry_run, force, runner=run_command):
    models = validate_preset(preset)
    models_dir = Path(models_dir)
    staging_root = models_dir / ".comfy-models-staging"
    plans = []
    for model in models:
        staging_dir = staging_root / model.name if model.provider == "huggingface" else None
        plan = plan_download(model, models_dir, staging_dir)
        if plan.destination and plan.destination.exists() and not force:
            print(f"skip {model.name}: {plan.destination} already exists")
            continue
        plans.append((model, plan))
    if dry_run:
        for model, plan in plans:
            print(f"install {model.name}: {' '.join(plan.command)}")
        return
    try:
        for model, plan in plans:
            if plan.destination:
                plan.destination.parent.mkdir(parents=True, exist_ok=True)
            print(f"install {model.name}: {' '.join(plan.command)}")
            runner(plan.command)
            if plan.staged_source:
                if not plan.staged_source.is_file():
                    raise PresetError(
                        f"downloaded file missing for {model.name}: {plan.staged_source}"
                    )
                shutil.move(str(plan.staged_source), str(plan.destination))
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
```

- [ ] **Step 4: Run the tests to verify the green state**

Run: `python3 -m unittest tests/test_comfy_models.py -v`

Expected: PASS for validation, dry-run, skip, and staging tests.

- [ ] **Step 5: Commit the installer**

```bash
git add scripts/comfy_models.py tests/test_comfy_models.py
git commit -m "feat: install models from presets"
```

### Task 3: Add the CLI entry point and the Krea 2 preset

**Files:**

- Modify: `scripts/comfy_models.py`
- Modify: `tests/test_comfy_models.py`
- Create: `presets/krea2-rtx3060.yaml`

- [ ] **Step 1: Write failing CLI and preset tests**

```python
class CliTests(unittest.TestCase):
    def test_cli_defaults_to_comfyui_models_directory(self):
        args = comfy_models.build_parser().parse_args(["install", "preset.yaml"])
        self.assertEqual(args.models_dir, "/opt/comfyui/models")
        self.assertFalse(args.dry_run)
        self.assertFalse(args.force)

    def test_krea_preset_has_the_three_required_types(self):
        preset_path = Path(__file__).parents[1] / "presets" / "krea2-rtx3060.yaml"
        models = comfy_models.validate_preset(comfy_models.load_preset(preset_path))
        self.assertEqual(
            [model.destination_directory for model in models],
            ["diffusion_models", "text_encoders", "vae"],
        )
```

- [ ] **Step 2: Run the tests to verify they fail for the expected reason**

Run: `python3 -m unittest tests/test_comfy_models.py -v`

Expected: FAIL because `build_parser` and `presets/krea2-rtx3060.yaml` are absent.

- [ ] **Step 3: Implement the entry point and create the approved preset**

Append this entry point to `scripts/comfy_models.py`:

```python
import argparse
import sys

def build_parser():
    parser = argparse.ArgumentParser(description="Install ComfyUI models from a YAML preset")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install", help="install models declared by a preset")
    install.add_argument("preset", help="path to a YAML preset")
    install.add_argument("--models-dir", default="/opt/comfyui/models")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--force", action="store_true")
    return parser

def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        install_models(load_preset(args.preset), args.models_dir, args.dry_run, args.force)
    except PresetError as error:
        print(f"comfy-models: {error}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

Create `presets/krea2-rtx3060.yaml`:

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

  - name: qwen3vl-4b-bf16
    type: text_encoder
    source:
      provider: huggingface
      repo_id: Comfy-Org/Krea-2
      filename: text_encoders/qwen3vl_4b_bf16.safetensors

  - name: qwen-image-vae
    type: vae
    source:
      provider: huggingface
      repo_id: Comfy-Org/Krea-2
      filename: vae/qwen_image_vae.safetensors
```

- [ ] **Step 4: Run the tests to verify the green state**

Run: `python3 -m unittest tests/test_comfy_models.py -v`

Expected: PASS, including the built-in preset test.

- [ ] **Step 5: Commit the CLI and preset**

```bash
git add scripts/comfy_models.py tests/test_comfy_models.py presets/krea2-rtx3060.yaml
git commit -m "feat: add Krea 2 model preset"
```

### Task 4: Bundle the feature in the Vast.ai image and document it

**Files:**

- Modify: `Dockerfile.vast`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `tests/test_comfy_models.py`

- [ ] **Step 1: Write a failing Dockerfile packaging test**

```python
class ImageDefinitionTests(unittest.TestCase):
    def test_vast_dockerfile_bundles_cli_and_presets(self):
        dockerfile = (Path(__file__).parents[1] / "Dockerfile.vast").read_text()
        self.assertIn("pip install --no-cache-dir pyyaml", dockerfile)
        self.assertIn("COPY scripts/comfy_models.py /usr/local/bin/comfy-models", dockerfile)
        self.assertIn("COPY presets/ /opt/comfyui/presets/", dockerfile)
```

- [ ] **Step 2: Run the test to verify it fails for the expected reason**

Run: `python3 -m unittest tests/test_comfy_models.py -v`

Expected: FAIL because `Dockerfile.vast` does not package the installer.

- [ ] **Step 3: Update the Dockerfile and documentation**

Add this block after Civitai CLI installation in `Dockerfile.vast`:

```dockerfile
RUN pip install --no-cache-dir pyyaml
COPY scripts/comfy_models.py /usr/local/bin/comfy-models
COPY presets/ /opt/comfyui/presets/
RUN chmod +x /usr/local/bin/comfy-models
```

Add this documentation to `README.md`:

```bash
comfy-models install --dry-run /opt/comfyui/presets/krea2-rtx3060.yaml
comfy-models install /opt/comfyui/presets/krea2-rtx3060.yaml
comfy-models install --models-dir /data/models /tmp/my-preset.yaml
```

Document that only the existing Hugging Face and Civitai token environment variables are used; no new environment variables are added. Document that a Civitai installation requires `--models-dir` to end in `models`.

Add `scripts/comfy_models.py` and `presets/` to the `AGENTS.md` key-files table and explain that the installer is only included in the Vast.ai custom image.

- [ ] **Step 4: Run the suite and a Dockerfile parse check**

Run: `python3 -m unittest tests/test_comfy_models.py -v`

Expected: PASS.

Run: `docker buildx build --platform=linux/amd64 --target nonexistent -f Dockerfile.vast .`

Expected: Docker reports that target `nonexistent` does not exist, with no `COPY` or Dockerfile syntax error.

- [ ] **Step 5: Commit image integration and docs**

```bash
git add Dockerfile.vast README.md AGENTS.md tests/test_comfy_models.py
git commit -m "feat: bundle Vast.ai preset installer"
```

## Plan self-review

- Each behavior has a test-first red/green sequence: validation, command planning, dry-run, skip behavior, staging moves, CLI defaults, preset content, and Docker packaging.
- The plan covers all three approved Krea 2 files and all specified paths.
- Provider tokens are never passed as command arguments or written to logs.

