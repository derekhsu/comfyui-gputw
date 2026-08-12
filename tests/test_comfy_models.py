import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "comfy_models.py"
SPEC = importlib.util.spec_from_file_location("comfy_models", SCRIPT)
comfy_models = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = comfy_models
SPEC.loader.exec_module(comfy_models)


class ValidationTests(unittest.TestCase):
    def hf_preset(self, filename="nested/flux.safetensors"):
        return {
            "version": 1,
            "name": "example",
            "models": [
                {
                    "name": "flux",
                    "type": "diffusion_model",
                    "source": {
                        "provider": "huggingface",
                        "repo_id": "org/repo",
                        "filename": filename,
                    },
                }
            ],
        }

    def test_hugging_face_model_maps_to_diffusion_models(self):
        model = comfy_models.validate_preset(self.hf_preset())[0]
        self.assertEqual(model.destination_directory, "diffusion_models")
        self.assertEqual(model.destination_filename, "flux.safetensors")

    def test_rejects_path_traversal_before_any_download(self):
        with self.assertRaisesRegex(comfy_models.PresetError, "path traversal"):
            comfy_models.validate_preset(self.hf_preset("../secret.safetensors"))

    def test_rejects_model_name_with_path_traversal(self):
        preset = self.hf_preset()
        preset["models"][0]["name"] = "../outside-models-dir"
        with self.assertRaisesRegex(comfy_models.PresetError, "model name"):
            comfy_models.validate_preset(preset)

    def test_hugging_face_plan_uses_a_staging_directory(self):
        model = comfy_models.validate_preset(self.hf_preset())[0]
        with tempfile.TemporaryDirectory() as temporary:
            models_dir = Path(temporary) / "models"
            staging_dir = models_dir / ".comfy-models-staging" / "flux"
            plan = comfy_models.plan_download(model, models_dir, staging_dir)
            self.assertEqual(
                plan.command,
                [
                    "hf",
                    "download",
                    "org/repo",
                    "nested/flux.safetensors",
                    "--local-dir",
                    str(staging_dir),
                ],
            )
            self.assertEqual(
                plan.destination,
                models_dir / "diffusion_models" / "flux.safetensors",
            )

    def test_civitai_plan_uses_comfyui_layout(self):
        preset = {
            "version": 1,
            "name": "civitai-example",
            "models": [
                {
                    "name": "style",
                    "type": "lora",
                    "source": {"provider": "civitai", "model_version_id": 123456},
                }
            ],
        }
        model = comfy_models.validate_preset(preset)[0]
        plan = comfy_models.plan_download(model, Path("/opt/comfyui/models"), None)
        self.assertEqual(
            plan.command,
            [
                "civitai",
                "download",
                "123456",
                "--layout",
                "comfyui",
                "--root",
                "/opt/comfyui",
            ],
        )


class InstallTests(unittest.TestCase):
    def preset(self):
        return {
            "version": 1,
            "name": "install-example",
            "models": [
                {
                    "name": "flux",
                    "type": "diffusion_model",
                    "source": {
                        "provider": "huggingface",
                        "repo_id": "org/repo",
                        "filename": "nested/flux.safetensors",
                    },
                }
            ],
        }

    def test_dry_run_prints_a_command_without_running_it(self):
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with redirect_stdout(output):
                comfy_models.install_models(
                    self.preset(),
                    Path(temporary) / "models",
                    dry_run=True,
                    force=False,
                    runner=calls.append,
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
                self.preset(),
                models_dir,
                dry_run=False,
                force=False,
                runner=calls.append,
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
                self.preset(),
                models_dir,
                dry_run=False,
                force=False,
                runner=runner,
            )
            self.assertEqual(
                (models_dir / "diffusion_models" / "flux.safetensors").read_text(),
                "model",
            )
            self.assertFalse((models_dir / ".comfy-models-staging").exists())


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


class ImageDefinitionTests(unittest.TestCase):
    def test_vast_dockerfile_bundles_cli_and_presets(self):
        dockerfile = (Path(__file__).parents[1] / "Dockerfile.vast").read_text()
        self.assertIn("pip install --no-cache-dir pyyaml", dockerfile)
        self.assertIn(
            "COPY scripts/comfy_models.py /usr/local/bin/comfy-models", dockerfile
        )
        self.assertIn("COPY presets/ /opt/comfyui/presets/", dockerfile)


if __name__ == "__main__":
    unittest.main()
