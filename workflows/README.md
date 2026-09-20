# Bundled Workflows

隨 image 出貨的現成 workflow，bake 進 base image 的 `/opt/comfyui/user/default/workflows/`。

## 前提：user-directory 行為（2026-08-22 實測）

- ComfyUI 預設 user dir = `/opt/comfyui/user`（`folder_paths.py:72`），啟動時動態建立
- UI Workflow 面板實際讀取 `<user-dir>/default/workflows/`（`default` 是單人模式的固定 username）
- 啟動帶 `--user-directory <path>` 時改讀 `<path>/default/workflows/`，**baked 的不會出現**

因此：

| 平台 | 啟動方式 | baked workflow 可見性 |
|---|---|---|
| vast.ai | 無 volume → **不要帶 `--user-directory`** | ✅ 開箱即用 |
| GPUtw | 有 `/vault` persistent volume → 帶 `--user-directory /vault/comfyui-user` | ❌ 需要時手動 cp |

## 檔案

| 檔案 | 格式 | 模型組合 | 用途 |
|---|---|---|---|
| `krea2_identity_edit_turbo.json` | editor（UI） | Turbo int8 + TE bf16 + wan VAE | 一般編輯（8 steps, CFG 1） |
| `api/krea2_identity_edit_turbo_api.json` | API | 同上 | 程式化執行（POST /api/prompt） |
| `api/krea2_identity_edit_raw_api.json` | API | Raw int8 + TE int8 + wan VAE | 移除類編輯（20 steps, CFG 3） |
| `qwen_image_2.1_t2i.json` | editor（UI） | Qwen-Image-2.1 int8 + TE int8 + bf16 VAE | 文生圖（native 2K, alpha） |
| `qwen_image_2.1_image_edit.json` | editor（UI） | 同上 | 指令式編輯（多圖參考 `<image1>`…`<image16>`） |

Qwen-Image-2.1 workflow 來源：官方 `Comfy-Org/workflow_templates`（`image_qwen_image_2_1_t2i` / `image_qwen_image_2_1_image_edit`）。需要 ComfyUI ≥ commit `6bfaacc`（PR #16400）；模型見 `presets/qwen-image-2.1-3090.yaml` / `qwen-image-2.1-5090.yaml`。5090 使用者可在 loader 把 diffusion 換成 `qwen_image_2.1_bf16.safetensors`。

Editor 版來源：節點包 `comfyui-krea2edit/workflows/krea2_identity_edit.json`。API 版已於 2026-08-22 在 instance 48375544 冒煙測試通過（turbo 版）。

需要 Identity Edit LoRA + Krea2Edit 節點包：見 `presets/krea2-identity-edit-*.yaml` 與 skill reference。
