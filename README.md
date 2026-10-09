# yanmai-video-reading

鄢麦视频读取 Skill：读取用户指定的抖音、小红书和本地视频，通过目标核对、媒体下载、截图查看与音频转写，提取有依据的内容。

用于核心内容提取、逐字稿、画面分析，以及判断视频中的事实、案例和演示方法能否作为创作素材。读取结果区分作者陈述、已核实事实与推断，支持独立表达。

## 安装到 Codex

将完整仓库放到技能目录；不要只复制 `SKILL.md`，配套脚本和参考文档也需要保留。

```bash
git clone https://github.com/SucRunBug/yanmai-video-reading.git \
  ~/.codex/skills/yanmai-video-reading
```

配置了自定义 `CODEX_HOME` 时，使用其 `skills/yanmai-video-reading` 目录。其他支持 `SKILL.md` 的 Agent 可按各自规则安装完整技能文件夹。

使用示例：

```text
使用 $yanmai-video-reading 读取这个视频，把核心观点、案例、需核实的数字
以及对我选题可用的素材整理到一个文件：<链接或本地路径>
```

## 能力与依赖

| 来源 / 环节 | 方法 | 需要什么 |
| --- | --- | --- |
| 抖音 | 浏览器观察指定视频实际媒体请求；处理 `other` 类型资源和音视频分轨 | 可观察资源 / 网络的浏览器、curl、FFmpeg、ffprobe |
| 小红书 | 解析同一笔记的公开手机分享页，匹配 ID，再下载当前媒体 | Python 3.9+、允许的网络访问、ffprobe |
| 本地画面 | 完整抽帧、实际 PTS 时间记录、联系表、指定时间补帧 | Python 3.9+、FFmpeg、ffprobe、Agent 的图片查看能力 |
| 音频 | 提取单声道 16 kHz WAV，再选择可用加速后端转写 | 实际可用的 ASR 工具；原始稿与清洗稿分别保留 |

三个命令行脚本仅使用 Python 标准库。语音模型不随仓库提供，也不会自动安装；Apple Silicon 优先检查 Metal / MLX，NVIDIA 优先检查 CUDA。

## 脚本用法

从仓库根目录执行。联网与安装操作遵守运行环境的权限规则。

```bash
# 检查 Python 与媒体工具，不发起网络请求
python3 scripts/fetch_xhs_video.py --check

# 小红书：每次从当前分享页取地址
python3 scripts/fetch_xhs_video.py '小红书分享链接' --output sources/xhs-example

# 本地视频：生成完整帧、联系表、时间记录和音频
python3 scripts/prepare_video.py sources/xhs-example/video.mp4 \
  --output output/xhs-example --audio

# 精细补看：使用新的输出目录
python3 scripts/prepare_video.py sources/xhs-example/video.mp4 \
  --output output/xhs-detail --interval 0.5 --at 6 15.2 24

# 抖音：浏览器观察到地址后，保存本地请求 JSON，再下载 / 合并
python3 scripts/download_douyin_media.py \
  --request sources/douyin-request.json --output sources/douyin-example
```

抖音请求 JSON 字段与浏览器步骤见 [抖音方法](references/douyin.md)。所有生成命令使用新建或空输出目录，避免覆盖已有材料。可通过 `--ffmpeg` / `--ffprobe` 指定当前机器的工具路径。

`prepare_video.py` 在 `media.json` 记录真实抽样帧的 PTS、指定时间实际取得的帧，以及每张联系表按从左到右、从上到下排列的帧文件。联系表方便定位，字幕和数字要打开完整单帧。它不做 OCR、语音转写或内容理解；`recognition_performed` 始终为 `false`，生成之后需要 Agent 实际读图 / 转写。

## 失败处理与边界

- 网页打不开不等于视频失效。先定位网络、跳转、页面解析、媒体请求和内容识别哪一层失败。
- 核对原链接与内容 ID，避免把推荐视频当目标；导航超时后先检查真实页面状态。
- 分轨视频要检查声音与同步；媒体签名过期时重新读取同一目标页面。
- 不绑定旧代理、Cookie、模型路径和浏览器配置，不关闭 HTTPS 校验。
- 页面字段和浏览器接口可能变化；私密、删除、登录和验证码限制需要相应授权或本地材料。
- 只采样部分画面就说明部分范围；音频转写不能代替视觉细节分析。

详见 [小红书方法](references/xiaohongshu.md)、[音频转写](references/transcription.md) 和 [失败处理](references/troubleshooting.md)。

`sources/`、`output/`、媒体、原始页面、日志和常见凭据文件已在 `.gitignore` 中排除。公开仓库只提供读取方法与工具；使用者仍需检查自己的提交内容。

## 验证记录

2026-10-09 在 macOS Apple Silicon 上验证：

- Skill 格式检查通过；14 项离线测试通过，涵盖目标 ID、推荐混入、登录重定向、字符串中的 `undefined`、域名边界、真实抽帧时间、单声道音频、缺失轨道、输出防覆盖和分轨合并。
- 使用已有的本地抖音视频测试抽帧与音频提取，实际打开约 8 秒画面核对 `CAO / Chief Agent Officer`。此次脚本验证没有重新浏览抖音。
- 小红书公开示例“肥牛滑蛋”下载成功，匹配笔记 ID `67f4e33e000000001b025337`，约 42.18 秒、720 × 1280。实际打开联系表与约 6 秒完整帧，看到“先打入3个鸡蛋”。
- 抖音浏览器资源观察、分轨下载和 MLX 转写方法来自先前实际操作；新合并脚本使用合成媒体测试。未重新对抖音做在线下载验证，也未在 Windows / Linux 上实测。

测试不保证平台未来接口不变。测试媒体和截图留在本地，不随开源仓库上传。

运行离线测试：

```bash
python3 -m unittest discover -s tests -v
```

## 来源与许可

小红书方法参考本人仓库 [SucRunBug/home-food 的 video-reading.md](https://github.com/SucRunBug/home-food/blob/78f7c7ae0c840b21fd43d207dca60266ceadaaa6/references/video-reading.md)，固定版本便于核对来源。这里将其公开手机页、目标 ID 核对、抽帧与失败处理经验整理为通用视频读取流程，配套脚本在本仓库实现。

本仓库采用 [MIT License](LICENSE)。
