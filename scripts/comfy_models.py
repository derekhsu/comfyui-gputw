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
