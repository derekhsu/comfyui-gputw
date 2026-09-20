# 從 RTX 3090 遷移到 RTX 5090：相容性分析

分析對象：`comfyui-gputw`（目前 pinned 版本 `v0.33.1-cu128-pt2.11.0`），部署目標從 Vast.ai 上的 RTX 3090 改為 RTX 5090。

最後更新：2026-09-05

---

## 結論摘要

**核心堆疊不需要改動。** 現有的 `cu128` + PyTorch 2.11.0 映像在 RTX 5090 上可以直接跑，不需要在映像內安裝驅動程式，也不需要升級 PyTorch。

需要處理的是這四件事：

1. **Host driver 版本**（唯一的硬性門檻，決定你能用 cu128 還是 cu130）
2. **Vast.ai 機器篩選**（5090 機器的 driver 不一定符合你要的 CUDA 變體）
3. **comfy-kitchen 的 NVFP4 後端**（cu128 下不可用，需要 cu130 + driver r580+ 才能解鎖）
4. **VRAM 從 24GB 變成 32GB**（反過來是好事，但啟動參數與 preset 選擇要跟著改）

---

## 1. 硬體與架構差異

| 項目 | RTX 3090 | RTX 5090 | 影響 |
| --- | --- | --- | --- |
| 架構 | Ampere (GA102) | Blackwell (GB202) | 全新微架構 |
| Compute Capability | `sm_86` (8.6) | `sm_120` (12.0) | **所有預編譯 CUDA kernel 都要重新對應** |
| VRAM | 24 GB GDDR6X | 32 GB GDDR7 | 模型卸載策略改變 |
| 記憶體頻寬 | 936 GB/s | ~1,790 GB/s | 顯著加速 |
| TDP | 350 W | 575 W | 散熱／供電穩定性風險 |
| Tensor Core | 第 3 代 | 第 5 代 | FP4/MXFP8 為新架構專屬 |
| 新增精度 | FP8 | **NVFP4 (FP4)、MXFP8** | 需要 comfy-kitchen + CUDA 13.0 |
| NVENC | 第 7 代 | 第 9 代（雙編碼器） | 影響 VideoHelperSuite 的編碼設定 |

關鍵差異是 `sm_86 → sm_120`。CUDA 的 binary (`cubin`) 是綁定特定 Compute Capability 的，任何只編到 sm_86 的 kernel 在 5090 上都無法載入，會丟 `CUDA error: no kernel image is available for execution on the device`。

---

## 2. 驅動程式：映像內不需要安裝，但 host driver 是硬門檻

### 映像內不用裝 driver

容器透過 `nvidia-container-toolkit` 掛載 host 的 driver library。**映像內不應該也不需要在 container 裡裝 NVIDIA driver** —— 這跟 3090 時期的做法完全一樣，沒有改變。

### 但 host driver 版本決定一切

CUDA 採用向下相容模型：container 內的 CUDA Runtime 版本必須 ≤ host driver 支援的版本。各變體的最低 driver 需求 [1][2]：

| 映像變體 | 最低 Linux driver | 備註 |
| --- | --- | --- |
| `cu128` | **570.26** | RTX 5090 能被認到的最低 driver 也是 570.x，所以 cu128 與 5090 的最低門檻剛好一致 |
| `cu129` | 575.51.03 | — |
| `cu130` | 580.65.06 | — |
| CUDA 13.3（目前最新） | 610.43.02 | 僅供參考，專案尚未使用 |

**這裡有個反直覺的結論：`cu128` 反而是 5090 上最保險的選擇。** 因為它對 driver 的要求最低（≥570），而 host driver 只要能認到 5090 就一定 ≥570。反之 `cu130` 需要 ≥580.65，若 Vast.ai 上那台 5090 機器的 driver 停在 570 或 575，`cu130` 映像會直接跑不起來。

### Vast.ai 上的做法

Vast.ai Console 的搜尋介面有 **Driver Version** 與 **Min Cuda Version** 兩個篩選欄位 [3]。租 5090 時：

- 要用 `vast-latest-cu128` → driver ≥ 570 即可
- 要用 `vast-latest-cu130` → 必須篩選 driver ≥ 580

---

## 3. CUDA 版本：cu128 已足夠，cu130 才能解鎖 NVFP4

### sm_120 的支援從 CUDA 12.8 開始

NVIDIA CUDA Toolkit 12.8 的 release notes 明確記載新增編譯器對 Blackwell 架構的支援，列出的架構包含 **`SM_100`、`SM_101`、`SM_120`** [1]。也就是說 CUDA 12.8 是首個原生支援 RTX 50 系列的 CUDA 版本，專案現有的 `cu128` 基礎映像剛好跨過這條線。

附帶一提，cuFFT 在 SM120 上對 legacy callback kernel 只有 PTX JIT 支援（非 LTO 的 device callback 必須編成 PTX 而非 SASS）[1]。ComfyUI 主線不會碰到，但若有 custom node 用到 cuFFT callback 是個潛在風險點。

### comfy-kitchen 是唯一的 cu130 誘因

ComfyUI v0.33.1 的 `requirements.txt` 已經內建 `comfy-kitchen==0.2.31` [4]。它是 Comfy-Org 的量化 kernel 函式庫，負責 NVFP4 / MXFP8 的路徑。它的需求是 [5]：

- **CUDA wheels 需要 CUDA Runtime ≥ 13.0，且預編譯 wheel 需要 NVIDIA driver r580+**
- 從 source 編譯則只需要 CUDA Toolkit ≥ 12.8
- 預設 CUDA arch 為 `75-virtual;80;89;90a;100f;120f`（Linux），已含 `120f`（Blackwell）
- NVFP4 (`TensorCoreNVFP4Layout`) 硬體需求為 SM ≥ 10.0

**這代表：在 `cu128` 映像上，comfy-kitchen 的 cuda backend 無法初始化，NVFP4 會降級到 triton 或 eager backend。** 影響是 `scaled_mm_nvfp4` 只有 cuda backend 有實作，所以在 cu128 上 NVFP4 量化模型只能拿到部分加速甚至完全無法使用。

若要完整發揮 5090 的 FP4 能力，需要：
- 映像切換到 `cu130`
- host driver ≥ 580

### FP4 帶來的實際差異

以 14B 模型為例，不同精度的 VRAM 佔用 [6]：

| 精度 | VRAM 佔用 |
| --- | --- |
| FP16 | ~28 GB |
| FP8 | ~14 GB |
| NVFP4 | ~6.8–7.5 GB |

5090 的 32GB 其實已經夠跑 FP16 的 14B 模型，所以 NVFP4 對本專案不是必需品，而是「要不要追求 2–3 倍推論速度」的選項。

---

## 4. PyTorch：現有版本已支援，不需要升級

- **PyTorch 2.7**（2025-04）正式加入 NVIDIA Blackwell 架構支援，並同時提供 CUDA 12.8 預編譯 wheel，隨附 Triton 3.3 也加入 Blackwell 支援 [7]。
- **PyTorch 2.11.0**（專案目前版本）的 release notes 中有多項 Blackwell 相關改進，包含 FlexAttention 的 FlashAttention-4 backend（Hopper 與 Blackwell）、cuDNN shape check 對 Blackwell 的支援、移除 Blackwell 上 `_scaled_mm` 的 layout check [8]。

**結論：`pt2.11.0 + cu128` 已包含 sm_120，不需要升級 PyTorch。**

### 但有一個新的陷阱要防

PyTorch 2.11 起，**PyPI 上的預設 torch wheel 改為 CUDA 13.0** [8]。這表示任何寫著 `torch`（未指定版本）的 `requirements.txt`，一旦 pip 觸發重新解析，就可能把映像裡的 cu128 torch 換成 cu130 torch —— 在 driver 只有 570/575 的機器上會直接崩潰。

本專案的 `custom-nodes.txt` 中，以下三個 node 的 requirements 含有未指定版本的 `torch`：

| Custom node | 風險內容 |
| --- | --- |
| `ComfyUI-SeedVR2_VideoUpscaler` | `torch`、`torchvision` 未指定版本 |
| `ComfyUI_LayerStyle` | `torch` 未指定版本 |
| `comfyui_controlnet_aux` | `torch`、`torchvision` 未指定版本，且含 `onnxruntime-gpu` |

正常情況下 pip 看到已安裝的 torch 會視為滿足約束而不動作，但這是隱性風險。**建議在 `Dockerfile.vast` 安裝 node requirements 後，加一步驗證 torch 版本與 CUDA build 沒有被換掉**（見第 8 節）。

---

## 5. Custom node 相依套件：目前全數安全

實測抓取 `custom-nodes.txt` 中所有 node 的 `requirements.txt`，**沒有任何一個要求 `xformers`、`flash-attn`、`triton` 或 `sageattention`**。這是好消息 —— 這四個正是 Blackwell 上最容易出問題的套件。

ComfyUI 主體的 `requirements.txt` 也**不含 xformers**（早已移除）[4]。

不過仍需注意以下套件在 sm_120 上的狀態，以備未來手動安裝或新增 node 時參考：

### flash-attn —— 仍無官方 sm_120 wheel

`pip install flash-attn` 的預編譯 wheel 至今不附 sm_120 binary [9]。目前沒有 node 依賴它，若日後加入需要 flash-attn 的 node，必須自行從 source 編譯（耗時）或改用第三方 wheel。推薦替代方案是 PyTorch 內建的 SDPA（啟動參數 `--use-pytorch-cross-attention`）或針對 sm_120 建的 SageAttention wheel。

### xformers —— 已支援，但不建議裝

xformers 從 **v0.0.33.post1**（2025-11）加入 cutlass fmha Op for Blackwell GPUs，v0.0.34 起改用 PyTorch stable ABI（針對 PyTorch 2.10+ 的 binary 可向後相容），最新版為 v0.0.35（2026-02）[10]。

社群上流傳「xformers 的 PyPI wheel 只支援到 sm_89」的說法 [6]，那是 2026 年初針對舊版本的描述，v0.0.33+ 之後已不成立。但 xformers 安裝時有可能拖動 torch 版本，而本專案根本沒用到它，**維持不裝是最省事的選擇**。

### SageAttention —— 需 sm_120 專屬 wheel，無官方 PyPI 套件

SageAttention 沒有官方 PyPI wheel，需要針對特定 torch / CUDA / Python 組合找對應的 wheel，版本錯一天就會 `DLL load failed` [6]。`ComfyUI-KJNodes` 的 Patch Sage Attention 節點是可選功能，未安裝 sageattention 時不會觸發。

若要用，建議的做法是**不要**用全域的 `--use-sage-attention`（在 Wan 2.1、Qwen 等模型上可能產生全黑輸出），而是在工作流中於模型載入後插入 KJNodes 的 Patch Sage Attention 節點，backend 設為 `sageattn_qk_int8_pv_fp16_cuda` [6]。

### Triton —— 已隨 PyTorch 帶入，但需要 C++ 編譯器

PyTorch 2.11 內附的 Triton 已支援 Blackwell。`Dockerfile` 已安裝 `gcc` + `python3-dev`，註解也說明這是 Triton JIT 首次使用時編譯 kernel 所需 [11] —— 這個需求在 5090 上完全相同，既有映像已具備。

### GGUF —— 不需要 llama-cpp-python，無編譯問題

`ComfyUI-GGUF` 現在做推論只需要 `pip install gguf`（純 Python）[12]，**不再需要 llama-cpp-python**。這消除了過去 GGUF 在 sm_120 上需要重編 llama-cpp-python 的麻煩。`presets/seedvr2-3b-q4km.yaml` 會用到這個 node，不受影響。

### onnxruntime-gpu —— 可能的隱性衝突

`comfyui_controlnet_aux` 的 requirements 含 `onnxruntime-gpu`，條件式在 Linux x86_64 上會安裝。它自帶 CUDA runtime library，在 `cu130` 環境下可能與映像內的 CUDA 13.0 runtime 衝突，或至少增加映像體積。切到 cu130 時建議特別觀察這個 node 是否正常。

---

## 6. VRAM 從 24GB 變 32GB 的連帶影響

### 啟動參數

32GB 下 ComfyUI 的 VRAM 分層策略閾值會改變。建議在 Vast.ai 的 startup args 加入：

```
--highvram
--async-offload
```

`--highvram` 讓模型常駐 VRAM（32GB 下合理），`--async-offload` 非同步搬移閒置 tensor。另有 `--pin-shared-memory`（鎖住 RAM pages 避免 swap 延遲）可視情況加入 [6]。

### preset 選擇可以改變

`presets/` 中有多個針對低 VRAM 設計的 int8 量化 preset，例如：

- `krea2-rtx3060.yaml` —— 使用 `krea2_turbo_int8_convrot` + `qwen3vl-4b-int8-convrot`
- `dark-beast-30-krea2-int8.yaml`、`moody-cutie-mix-krea2-v40-int8.yaml` 等一系列 `-int8` preset

這些是為了 3060 的 12GB 設計的。5090 的 32GB 可以直接跑完整精度版本，**畫質會明顯提升**。建議後續新增非量化版本的 preset。

### 功耗與穩定性

5090 的 575W TDP 遠高於 3090 的 350W。在 Vast.ai 這種多卡主機上，高負載（特別是高解析度影片生成）可能因供電或散熱導致 driver 崩潰。社群回報在高 VRAM 佔用的重載下出現過畫面黑掉、driver crash 的情況 [6]。建議上線後監控 `nvidia-smi` 的溫度與 power draw。

---

## 7. 決策表：該選哪個映像

| 情境 | 建議映像 | Host driver 需求 | 可獲得 |
| --- | --- | --- | --- |
| 先求能跑，不想動任何東西 | `vast-latest-cu128` | ≥ 570 | 完整 sm_120 原生 kernel，NVFP4 降級為 triton/eager |
| 要完整 NVFP4 / FP4 加速 | `vast-latest-cu130` | **≥ 580** | comfy-kitchen cuda backend 全開 |
| Host driver 卡在 570/575 | `vast-latest-cu128` | ≥ 570 | 同上，cu130 在此會直接失敗 |

---

## 8. 上線前的驗證步驟

### 8.1 在 Vast.ai 上開一台 5090，用 SSH 模式進容器

注意：SSH 模式會取代 image ENTRYPOINT，記得在 on-start script 明確呼叫 `/opt/entrypoint-wrapper.sh`，並用 `nohup` 讓 ComfyUI 在背景跑 [11]。

### 8.2 確認 torch 的 CUDA build 與 arch 支援

```bash
python3 -c "
import torch
print('torch:', torch.__version__)
print('cuda:', torch.version.cuda)
print('arch list:', torch.cuda.get_arch_list())
print('device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO GPU')
print('capability:', torch.cuda.get_device_capability(0))
"
```

**重點檢查**：`torch.version.cuda` 必須是 `12.8`（不是 13.0），`get_arch_list()` 必須包含 `sm_120`。若 PyTorch 有把 arch 編進去但沒有 sm_120 的 cubin，就會在執行時炸 `no kernel image`。

### 8.3 確認 comfy-kitchen backend

```bash
python3 -c "
import comfy_kitchen as ck
print('backends:', ck.list_backends())
" 2>&1 | grep -v "^CUDA banner"
```

在 cu128 上 `cuda` backend 會缺席或載入失敗；在 cu130 + driver r580+ 上應該要能列出 `cuda`。

### 8.4 實際跑一次推論

用 `comfy-models install /opt/comfyui/presets/krea2-rtx3060.yaml` 裝一組模型，跑一次生成。VAE decode 是 sm_120 相容性問題最常浮現的地方 [6]，務必測到。

### 8.5 檢查 custom node 載入失敗

```bash
python3 main.py --listen 0.0.0.0 --port 8080 2>&1 | grep -iE "error|fail|no kernel|sm_120"
```

---

## 9. 需要修改的檔案

若不切換 CUDA 變體（維持 cu128），**專案檔案完全不需要改動**。

若決定切到 cu130，需要：

| 檔案 | 修改 |
| --- | --- |
| CI workflow dispatch | `pytorch_cuda_tag=cu130`，並重建 `vast-` 變體 |
| `Dockerfile` | `CUDA_BASE_IMAGE=nvidia/cuda:13.0.0-runtime-ubuntu22.04` |
| `README.md` / `AGENTS.md` | 更新 host requirements 的最低 driver 說明（580.65+） |

另外建議（非必要）：在 `Dockerfile.vast` 安裝 custom node requirements 之後，加入一步 torch 版本斷言，防止 `torch` 被 pip 換成 cu130：

```dockerfile
RUN python3 -c "import torch; assert torch.version.cuda == '${CUDA_RUNTIME_VERSION}', torch.version.cuda"
```

---

## 參考資料

[1] NVIDIA, "CUDA Toolkit 12.8 Release Notes" — https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html（存取日期 2026-09-05）

[2] NVIDIA, "CUDA Toolkit 13.3 Update 1 Release Notes"（表 3：CUDA Toolkit 與對應 driver 版本）— https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html（存取日期 2026-09-05）

[3] Vast.ai, "Console"（機器搜尋介面含 Driver Version / Min Cuda Version 篩選）— https://cloud.vast.ai/（存取日期 2026-09-05）

[4] Comfy-Org, "ComfyUI v0.33.1 requirements.txt" — https://raw.githubusercontent.com/comfyanonymous/ComfyUI/v0.33.1/requirements.txt（存取日期 2026-09-05）

[5] Comfy-Org, "comfy-kitchen README"（Backend Capabilities Matrix、Requirements 一節）— https://github.com/Comfy-Org/comfy-kitchen（存取日期 2026-09-05）

[6] lilting channel, "ComfyUI 'no kernel image is available' on RTX 5090 and Blackwell" — https://lilting.ch/en/articles/comfyui-blackwell-gpu-compatibility（存取日期 2026-09-05）

[7] PyTorch Team, "PyTorch 2.7 Release"（Prototype: NVIDIA Blackwell Architecture Support）— https://pytorch.org/blog/pytorch-2-7/（存取日期 2026-09-05）

[8] PyTorch, "Release v2.11.0" — https://github.com/pytorch/pytorch/releases/tag/v2.11.0（存取日期 2026-09-05）

[9] HenryZ838978, "flash-attn-blackwell"（Pre-built Flash Attention wheels for Blackwell sm_120）— https://github.com/HenryZ838978/flash-attn-blackwell（存取日期 2026-09-05）

[10] facebookresearch, "xformers Releases" — https://github.com/facebookresearch/xformers/releases（存取日期 2026-09-05）

[11] comfyui-gputw, "AGENTS.md" / "Dockerfile"（本專案）— /Volumes/extension_data/Project/comfyui-gputw/（存取日期 2026-09-05）

[12] city96, "ComfyUI-GGUF README" — https://github.com/city96/ComfyUI-GGUF（存取日期 2026-09-05）

[13] Docker Hub, "derekhsu/comfyui-gputw tags" — https://hub.docker.com/r/derekhsu/comfyui-gputw/tags（存取日期 2026-09-05）
