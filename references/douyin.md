# 抖音：读取指定视频与核对截图

## 1. 先固定视频身份

保存用户给的分享链接。用可用浏览器打开它，等页面加载并播放，记录解析后的 `/video/<id>`、作者、标题。页面时长只是线索，下载后以 ffprobe 为准。

标题、搜索摘要、平台 AI 章节和评论只能辅助定位。不要把它们当逐字稿。如果页面显示其他视频，立即核对 URL 与 ID；短链接初始跳转、推荐点击和实际目标必须能对应。

浏览器选择遵守用户指定的浏览器和当前工具文档。以 Codex 的 `cua` 为例，首次或重置后调用按该工具要求只做一次入口调用：

```javascript
let tab = await cua.createBrowserTab("iab", shareUrl, { visible: false });
```

有用户指定的已有标签页时，使用对应的 `getTab` 入口。后续先读返回的文档与状态，再调用工具；打开声音、点击播放等操作使用当前状态中的元素。是否显示窗口取决于用户需求。

## 2. 观察真实媒体请求

使用当前浏览器的 Network 或资源观察能力。目标是本次播放实际请求的 `*.douyinvod.com` URL；不要从其他视频、页面推荐或旧缓存拼地址。

本次验证过的 Codex 浏览器路径是 `pageAssets`：

```javascript
let assets = await tab.capabilities.get("pageAssets");
let inventory = await assets.list();
let candidates = inventory.assets.filter(
  item => /(^|\.)douyinvod\.com$/i.test(new URL(item.url).hostname)
);
```

先查看该能力的当前文档和输出，再取实际 URL；API 可随工具版本变化。媒体资源可能被归类为 `other`，不能只过滤 `kind === "video"`。浏览器资源打包出现 `unsupported asset kinds` 时，保留已观察到的 URL，改用本地下载，不反复打包。

常见命名：

- `media-video-*`：视频轨，可能为 `hvc1` / HEVC 或 H.264。
- `media-audio-*`：音频轨，可能为 `mp4a` / AAC。

命名只用于筛选，必须检查实际下载后的媒体轨。若音视频已在同一文件，不必强行拆分。拿不到请求时，确认同一目标是否已播放，刷新资源列表。只有浏览器路径不可用时，才尝试当前环境已经可用的其他下载工具；不要反复耗在 Cookie 报错上。

## 3. 下载、合并与检查

使用当前浏览器 User-Agent 和目标视频 Referer。URL 常带短期签名：保存在本地临时 JSON，避免写进仓库、报告正文或命令历史。示例文件只含占位值：

```json
{
  "page_url": "https://www.douyin.com/video/CONTENT_ID",
  "user_agent": "CURRENT_BROWSER_USER_AGENT",
  "video_url": "OBSERVED_VIDEO_URL",
  "audio_url": "OBSERVED_AUDIO_URL"
}
```

`page_url` 要换成实际数字 ID；复用已合轨文件时省略 `audio_url`。

```bash
python3 scripts/download_douyin_media.py --request sources/request.json --output sources/target
```

脚本通过 curl 下载，检查视频与音频轨，用 FFmpeg 的显式映射合并，再写 `video.mp4` 与不含签名地址的 `source.json`。它不打开页面，也不自动找链接。

对应的分轨合并原理：

```bash
ffmpeg -i video_track.mp4 -i audio_track.m4a \
  -map 0:v:0 -map 1:a:0 -c copy video.mp4
```

检查时长、分辨率、编解码器和轨道。音视频时长明显不同、静音、音画错位时，先核对两个地址是否属于同一目标，重新抓取，不能靠截短掩盖错对象。

## 4. 从截图读到内容

用 `prepare_video.py` 取完整画面与联系表，再实际打开图片。联系表用于定位，字幕、小字、数字必须看原尺寸单帧。必要时加密抽帧或指定时间。

本次实例中，约 8 秒画面显示 `CAO / Chief Agent Officer`；音频识别成 `CAA` 时，依据该画面修正。约 38 秒术语卡片同时列出 `Prompt / FDE / CAO`，这类画面可核对术语。实例时间只解释核对方法，不是其他视频的固定取帧时间。

截图说明“视频写了什么”，不能单独证明薪资、招聘需求或商业收益真实。用户要求研究素材时，为这类主张另找可核查出处。

## 实际失败带来的处理顺序

- 普通网页工具打不开分享链接：换可用浏览器打开同一目标；不据此宣称视频删除。
- 浏览器打包拒绝 `other` 媒体资源：用实际观察到的地址分别下载。
- 下载看起来成功但没有声音：检查音轨；抖音 Web 播放可能分轨。
- 沙箱连接代理失败：区分执行环境的联网权限与代理服务本身；走当前正常授权流程，不写死旧端口。
- 页面导航超时 / 工具重置：先检查当前实际 URL 与状态。超时不代表导航没发生；重新绑定目标后再读取。
- 用户说读错了：优先对齐内容 ID、作者、标题与关键帧，并修正已写结论。

默认只读取指定视频。需要另外找对标时，按用户授权另做检索并明确标注新来源；用户要求停止抖音调研时，停止平台导航，继续使用已存本地材料。
