#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys

import yaml


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
        return Model(
            name=name,
            provider=provider,
            destination_directory=TYPE_DIRECTORIES[model_type],
            model_version_id=str(version_id),
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
    return DownloadPlan(
        command=[
            "civitai",
            "download",
            model.model_version_id,
            "--layout",
            "comfyui",
            "--root",
            str(models_dir.parent),
        ],
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


def run_command(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as error:
        raise PresetError(f"required executable not found: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        raise PresetError(
            f"provider command failed ({error.returncode}): {' '.join(command)}"
        ) from error


def install_models(
    preset: object,
    models_dir: Path | str,
    *,
    dry_run: bool,
    force: bool,
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        install_models(
            load_preset(args.preset),
            args.models_dir,
            dry_run=args.dry_run,
            force=args.force,
        )
    except PresetError as error:
        print(f"comfy-models: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
