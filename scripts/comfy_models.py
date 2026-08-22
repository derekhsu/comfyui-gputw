#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import time

import yaml


TYPE_DIRECTORIES = {
    "diffusion_model": "diffusion_models",
    "text_encoder": "text_encoders",
    "vae": "vae",
    "checkpoint": "checkpoints",
    "lora": "loras",
    "controlnet": "controlnet",
    "upscale_model": "upscale_models",
    "seedvr2": "SEEDVR2",
}

PID1_SECRET_VARS = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "CIVITAI_API_KEY",
    "CIVITAI_TOKEN",
)
PID1_ENVIRON = Path("/proc/1/environ")


class PresetError(ValueError):
    """Raised when a preset cannot be safely installed."""


@dataclass(frozen=True)
class Model:
    name: str
    provider: str
    destination_directory: str
    repo_id: str | None = None
    filename: str | None = None
    revision: str | None = None
    model_version_id: str | None = None
    file: str | int | None = None

    @property
    def destination_filename(self) -> str | None:
        return PurePosixPath(self.filename).name if self.filename else None


@dataclass(frozen=True)
class DownloadPlan:
    command: list[str]
    destination: Path | None
    staged_source: Path | None


def require_non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PresetError(f"{field} must be a non-empty string")
    return value


def validate_preset(preset: object) -> list[Model]:
    if not isinstance(preset, dict):
        raise PresetError("preset must be a mapping")
    if type(preset.get("version")) is not int or preset["version"] != 1:
        raise PresetError("version must be integer 1")
    require_non_empty(preset.get("name"), "name")
    models = preset.get("models")
    if not isinstance(models, list) or not models:
        raise PresetError("models must be a non-empty list")
    return [validate_model(raw, index) for index, raw in enumerate(models, start=1)]


def validate_model(raw: object, index: int) -> Model:
    if not isinstance(raw, dict):
        raise PresetError(f"models[{index}] must be a mapping")
    name = require_non_empty(raw.get("name"), f"models[{index}].name")
    name_path = PurePosixPath(name)
    if name_path.is_absolute() or "/" in name or ".." in name_path.parts:
        raise PresetError("model name contains path traversal")
    model_type = require_non_empty(raw.get("type"), f"models[{index}].type")
    if model_type not in TYPE_DIRECTORIES:
        raise PresetError(f"unsupported model type: {model_type}")
    source = raw.get("source")
    if not isinstance(source, dict):
        raise PresetError(f"models[{index}].source must be a mapping")
    provider = require_non_empty(source.get("provider"), f"models[{index}].source.provider")

    if provider == "huggingface":
        repo_id = require_non_empty(source.get("repo_id"), "huggingface repo_id")
        filename = require_non_empty(source.get("filename"), "huggingface filename")
        file_path = PurePosixPath(filename)
        if file_path.is_absolute() or ".." in file_path.parts:
            raise PresetError("huggingface filename contains path traversal")
        revision = source.get("revision")
        if revision is not None:
            revision = require_non_empty(revision, "huggingface revision")
        return Model(
            name=name,
            provider=provider,
            destination_directory=TYPE_DIRECTORIES[model_type],
            repo_id=repo_id,
            filename=filename,
            revision=revision,
        )

    if provider == "civitai":
        version_id = source.get("model_version_id")
        if (
            not isinstance(version_id, (str, int))
            or isinstance(version_id, bool)
            or not str(version_id)
        ):
            raise PresetError("civitai model_version_id must be a string or integer")
        # Optional file selector: a numeric file id or a filename substring.
        # Civitai versions can ship multiple files (e.g. fp8/fp16/gguf of the
        # same model); without --file the CLI downloads the primary file only.
        # When files share a name, use the numeric file id (from the
        # model-versions API) to disambiguate.
        file_value = source.get("file")
        if file_value is not None:
            if isinstance(file_value, bool) or not isinstance(file_value, (str, int)):
                raise PresetError("civitai file must be a string or integer")
            if not str(file_value).strip():
                raise PresetError("civitai file must be a non-empty string or integer")
        return Model(
            name=name,
            provider=provider,
            destination_directory=TYPE_DIRECTORIES[model_type],
            model_version_id=str(version_id),
            file=file_value,
        )

    raise PresetError(f"unsupported provider: {provider}")


def plan_download(
    model: Model, models_dir: Path | str, staging_dir: Path | str | None
) -> DownloadPlan:
    models_dir = Path(models_dir)
    if model.provider == "huggingface":
        command = ["hf", "download", model.repo_id, model.filename]
        if model.revision:
            command.extend(["--revision", model.revision])
        command.extend(["--local-dir", str(staging_dir)])
        return DownloadPlan(
            command=command,
            destination=models_dir / model.destination_directory / model.destination_filename,
            staged_source=Path(staging_dir) / PurePosixPath(model.filename),
        )

    if models_dir.name != "models":
        raise PresetError("Civitai requires --models-dir to end in 'models'")
    command = [
        "civitai",
        "download",
        model.model_version_id,
        "--layout",
        "comfyui",
        "--root",
        str(models_dir.parent),
    ]
    if model.file is not None:
        command.extend(["--file", str(model.file)])
    return DownloadPlan(
        command=command,
        destination=None,
        staged_source=None,
    )


def load_preset(path: Path | str) -> object:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except OSError as error:
        raise PresetError(f"cannot read preset: {error}") from error
    except yaml.YAMLError as error:
        raise PresetError(f"invalid YAML: {error}") from error


def provider_environment() -> dict[str, str]:
    """Return the current environment plus Vast.ai PID 1 secrets."""
    environment = os.environ.copy()
    try:
        entries = PID1_ENVIRON.read_bytes().split(b"\0")
    except OSError:
        entries = []

    for entry in entries:
        if b"=" not in entry:
            continue
        key_bytes, value_bytes = entry.split(b"=", 1)
        key = os.fsdecode(key_bytes)
        if key in PID1_SECRET_VARS and key not in environment:
            environment[key] = os.fsdecode(value_bytes)

    # Civitai CLI v0.1.81 expects CIVITAI_TOKEN. Vast.ai commonly names the
    # account variable CIVITAI_API_KEY, so provide the compatible alias.
    if "CIVITAI_TOKEN" not in environment and "CIVITAI_API_KEY" in environment:
        environment["CIVITAI_TOKEN"] = environment["CIVITAI_API_KEY"]
    return environment


def run_command(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, env=provider_environment())
    except FileNotFoundError as error:
        raise PresetError(f"required executable not found: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        raise PresetError(
            f"provider command failed ({error.returncode}): {' '.join(command)}"
        ) from error


def fetch_civitai_metadata(version_id: str) -> dict:
    """Fetch a civitai model version's metadata as JSON via `civitai mv get`."""
    try:
        result = subprocess.run(
            ["civitai", "mv", "get", str(version_id), "--json"],
            capture_output=True,
            text=True,
            check=True,
            env=provider_environment(),
        )
        return json.loads(result.stdout)
    except FileNotFoundError as error:
        raise PresetError("required executable not found: civitai") from error
    except subprocess.CalledProcessError as error:
        raise PresetError(
            f"civitai metadata fetch failed ({error.returncode}): {error.stderr.strip()}"
        ) from error
    except json.JSONDecodeError as error:
        raise PresetError(f"civitai metadata parse failed: {error}") from error


def _find_civitai_file(meta: dict, file_selector: str | int | None) -> dict | None:
    """Find the downloaded file entry in civitai metadata."""
    files = meta.get("files") or []
    if file_selector is not None:
        file_str = str(file_selector)
        for f in files:
            if str(f.get("id")) == file_str:
                return f
        for f in files:
            if file_str in (f.get("name") or ""):
                return f
    for f in files:
        if f.get("primary"):
            return f
    return files[0] if files else None


def install_civitai_sidecar(model: Model, models_dir: Path, *, dry_run: bool) -> None:
    """Download preview image and write .metadata.json sidecar for a civitai model.

    Generates the sidecar files expected by ComfyUI-Lora-Manager:
    - ``<basename>.<ext>``  — first preview image from the Civitai version
    - ``<basename>.metadata.json`` — structured metadata (see Lora Manager schema)

    Failures are non-fatal: the model itself was already downloaded, so sidecar
    errors only emit a stderr warning and do not abort the install.
    """
    if dry_run:
        print(f"sidecar {model.name}: would fetch metadata, download preview, write .metadata.json")
        return

    try:
        meta = fetch_civitai_metadata(model.model_version_id)
    except PresetError as error:
        print(f"sidecar {model.name}: {error}", file=sys.stderr)
        return

    target = _find_civitai_file(meta, model.file)
    if not target or not target.get("name"):
        print(f"sidecar {model.name}: no file found in metadata, skipping", file=sys.stderr)
        return

    filename = target["name"]
    model_path = (models_dir / model.destination_directory / filename).resolve()
    basename = model_path.stem

    # Download the first preview image (same-basename sidecar, original extension).
    preview_filename = None
    preview_nsfw_level = 0
    images = meta.get("images") or []
    if images:
        img_url = images[0].get("url")
        if img_url:
            ext = PurePosixPath(img_url.split("?")[0]).suffix or ".png"
            preview_filename = f"{basename}{ext}"
            preview_path = model_path.parent / preview_filename
            try:
                subprocess.run(
                    ["curl", "-fL", "-s", "-o", str(preview_path), img_url],
                    check=True,
                    env=provider_environment(),
                )
                print(f"sidecar preview {model.name}: {preview_path}")
            except (subprocess.CalledProcessError, FileNotFoundError) as error:
                msg = f"exit {error.returncode}" if isinstance(error, subprocess.CalledProcessError) else "curl not found"
                print(f"sidecar preview {model.name}: download failed ({msg})", file=sys.stderr)
                preview_filename = None
            preview_nsfw_level = images[0].get("nsfwLevel", 0)

    # Write .metadata.json (ComfyUI-Lora-Manager schema).
    try:
        size = model_path.stat().st_size
    except OSError:
        size = 0

    model_meta = meta.get("model") or {}
    metadata: dict = {
        "file_name": basename,
        "model_name": model_meta.get("name", basename),
        "file_path": str(model_path),
        "size": size,
        "modified": time.time(),
        "base_model": meta.get("baseModel", ""),
        "from_civitai": True,
        "civitai": meta,
        "tags": model_meta.get("tags", []),
        "modelDescription": model_meta.get("description", ""),
        "metadata_source": "civitai",
        "trainedWords": meta.get("trainedWords", []),
        "hash_status": "completed",
    }
    if preview_filename:
        metadata["preview_url"] = preview_filename
        metadata["preview_nsfw_level"] = preview_nsfw_level
    # LoRA models do not carry model_type; checkpoints/diffusion_models do.
    if model.destination_directory == "diffusion_models":
        metadata["model_type"] = "diffusion_model"
    elif model.destination_directory == "checkpoints":
        metadata["model_type"] = "checkpoint"

    metadata_path = model_path.parent / f"{basename}.metadata.json"
    try:
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"sidecar metadata {model.name}: {metadata_path}")
    except OSError as error:
        print(f"sidecar metadata {model.name}: write failed: {error}", file=sys.stderr)


def install_models(
    preset: object,
    models_dir: Path | str,
    *,
    dry_run: bool,
    force: bool,
    sidecar: bool = True,
    runner=run_command,
) -> None:
    models = validate_preset(preset)
    models_dir = Path(models_dir)
    staging_root = models_dir / ".comfy-models-staging"
    plans: list[tuple[Model, DownloadPlan]] = []

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
            if model.provider == "civitai" and sidecar:
                install_civitai_sidecar(model, models_dir, dry_run=True)
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
            if model.provider == "civitai" and sidecar:
                install_civitai_sidecar(model, models_dir, dry_run=False)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install ComfyUI models from a YAML preset"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    install = subcommands.add_parser("install", help="install models declared by a preset")
    install.add_argument("preset", help="path to a YAML preset")
    install.add_argument(
        "--models-dir", default="/opt/comfyui/models", help="ComfyUI models directory"
    )
    install.add_argument("--dry-run", action="store_true", help="print commands only")
    install.add_argument("--force", action="store_true", help="redownload existing files")
    install.add_argument(
        "--no-sidecar",
        action="store_true",
        help="skip civitai preview image and .metadata.json sidecar download",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        install_models(
            load_preset(args.preset),
            args.models_dir,
            dry_run=args.dry_run,
            force=args.force,
            sidecar=not args.no_sidecar,
        )
    except PresetError as error:
        print(f"comfy-models: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
