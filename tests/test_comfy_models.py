import importlib.util
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
