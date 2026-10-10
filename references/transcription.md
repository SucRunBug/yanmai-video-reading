# 音频转写与清洗

## 先检查加速条件

提取 / 复用音频轨，然后检查机器架构、当前 Python 与已有包。

- Apple Silicon：优先已有 MLX / Metal、whisper.cpp Metal 或 CoreML。MLX 可以检查 `mlx.core.metal.is_available()`；导入失败和返回不可用是不同的问题。
- NVIDIA：检查已有驱动、CUDA 与 faster-whisper 的 GPU 支持，使用兼容环境。
- 无加速、准备成本明显过高或极短任务：可以 CPU 转写，说明实际后端。

包离线安装失败时，先检查当前 Python 版本与已缓存轮子的兼容性。本次实际出现过默认环境无法离线解析，但换已有兼容环境后 MLX 可以使用的情况。不要绑定复现机器的具体 Python 路径与模型缓存目录。

## 示例：已安装 MLX Whisper

这段供已有 `mlx-whisper` 环境使用，不会自动安装依赖。`model_path_or_repo` 使用本机现有模型路径或用户允许下载的模型标识。

```python
import json
from pathlib import Path
import mlx.core as mx
import mlx_whisper

if not mx.metal.is_available():
    raise RuntimeError("当前环境没有可用 Metal 后端，请重新选择转写路径")

out = Path("output/transcription")
out.mkdir(parents=True, exist_ok=False)
result = mlx_whisper.transcribe(
    "output/target/audio.wav",
    path_or_hf_repo=model_path_or_repo,
    language="zh",  # 根据实际语言调整，不强制所有视频中文
    initial_prompt="Agent, Prompt, FDE, CAO",  # 仅填确有依据的术语
    condition_on_previous_text=False,
    verbose=False,
)
(out / "asr_raw.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
(out / "asr_raw.txt").write_text(result["text"], encoding="utf-8")
```

其他后端同样保留原始文本、分段时间与后端 / 模型信息。模型标识、提示词与识别结果都需要记录在本地，不假定一个模型适合所有素材。

## 清洗要求

至少保留 `asr_raw.txt` 与 `asr_clean.txt`（或 Markdown）。原始稿不覆盖。清洗稿必须是保留完整原话、口语和顺序的逐字稿；只加标点、修正明确错字、产品名与技术词，不压缩为摘要，也不为通顺重写观点。

画面里的 `CAO / Chief Agent Officer` 可纠正 ASR 的 `CAA`；仅凭语感猜到的英文词不能当作确定修正。数字、金额与岗位名优先核对字幕和对应音频，听不清时标为 `[听不清，约 00:38]`。

忽略静音处无依据的重复句或幻觉时，在清洗说明里记录。用户只要求文字稿时，交付两个稿件及简短范围说明即可；需要视频分析或资料挖掘时，按 [视频分析交付格式](video-analysis.md) 将各段逐字稿放在对应线索前，来源与存疑标注放在引文之外。
