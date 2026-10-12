# B 站：公开接口获取同一 BV / CID 的音视频

适用于完整 `bilibili.com/video/BV…` 链接或 BV 号。短链接先用当前允许的工具解析成可核对的 BV 页面。已有媒体时直接复用。这里记录的是实测成功的公开接口路径，不依赖网页登录；接口会变化，访问受限时换同一目标的浏览器或已有本地材料。

## 首选路径

1. 从用户原链接提取 BV 号。保留原分享链接，生成去掉跟踪参数的规范页面地址；分 P 链接保留 `p=N`，不能默认为其他分 P。
2. 请求 `https://api.bilibili.com/x/web-interface/view?bvid=BV…`。先检查 `code == 0`，核对返回 `data.bvid`，再从 `data.pages` 选目标分 P 的 `cid`。记录作者、标题、发布时间、页面时长。不要从 `ugc_season.sections[].episodes` 的推荐 / 合集内容里另挑视频。
3. 请求同一 BV / CID 的 `x/player/playurl`，已验证参数为 `bvid`、`cid`、`qn=64`、`fnval=16`、`fourk=0`。从实际返回的 `data.dash.video` 与 `data.dash.audio` 选择轨道；H.264 优先，音频选择较高带宽。
4. 读取当前轨道中的 `baseUrl` / `base_url`，必要时取该轨道的 `backupUrl` / `backup_url`。带 User-Agent 和原视频页面 Referer 分别下载音视频。媒体通常来自 `*.bilivideo.com` 或 `*.bilivideo.cn`；只接受当前返回的允许域名 HTTPS 地址。
5. ffprobe 分别核对轨道与时长，再用 FFmpeg 显式选轨合并，不重新编码：

```bash
ffmpeg -i video-track.m4s -i audio-track.m4s \
  -map 0:v:0 -map 1:a:0 -c copy video.mp4
```

6. 检查最终文件同时有视频轨与音频轨，记录实际时长。请求 `x/player/v2?bvid=BV…&cid=…` 查看 `data.subtitle.subtitles`。空列表只表示本次公开接口没提供字幕，继续用完整音频 ASR 与嵌入字幕；接口失败也不否定已下载的音视频。

`qn` 是请求参数，不能直接当作拿到的画质。应以实际返回格式和 ffprobe 为准；不假定未登录也能取得 1080p，不尝试提升账号权限。

## 可复用脚本

```bash
# 只检查依赖
python3 scripts/fetch_bilibili_video.py --check

# 当前目标：公开信息 → DASH 下载 → 分轨合并 → 字幕可用性记录
python3 scripts/fetch_bilibili_video.py 'USER_BV_URL_OR_ID' \
  --output sources/bilibili-target

# 用户明确指定的分 P
python3 scripts/fetch_bilibili_video.py 'USER_BV_URL_OR_ID' \
  --page 2 --output sources/bilibili-part-2

# 完整画面采样、联系表、真实时间戳和单声道音频
python3 scripts/prepare_video.py sources/bilibili-target/video.mp4 \
  --output output/bilibili-target --audio
```

依赖 Python 3.9+、curl、FFmpeg、ffprobe。可用 `--ffmpeg` / `--ffprobe` 指定工具，`--user-agent` 指定当前浏览器 UA；脚本不会改代理、登录、安装模型或关闭 HTTPS 校验。

输出必须是新建或空目录。脚本保留接口响应、选择的视频信息、分轨、最终视频和 `source.json`；标准输出只报告本地视频路径。接口响应可能很大，且 `playurl-api.json` 含会过期的签名地址，只留本地，不整段打印或公开。

脚本当前实现已验证的 DASH 路径。没有 DASH 或没有公开可用的两条轨道时停止并提示换路径；不猜测未验证的其他媒体格式。每条轨道最多尝试两个当前返回的地址。字幕记录区分 `empty`、`available`、`unavailable`；`available` 仅表示接口提供条目，脚本不会自行下载或声称已阅读字幕。

## 本次遇到的错误与解决思路

| 现象 | 实际判断与处理 |
| --- | --- |
| 网页读取工具报 `Internal Error` / 页面不可访问，BV 号搜索无结果 | 不能据此判断视频失效。改请求同一 BV 的公开信息接口，成功取得标题、作者、CID 与时长。 |
| 浏览器创建页面超时，工具会话重置 | 导航超时不能当作读过页面。会话仍在时先检查状态；已重置则按工具规则重新绑定。本次后续公开接口成功，因此没有继续依赖浏览器。 |
| 信息接口输出异常庞大 | `ugc_season` 包含大量合集视频。将完整响应保存本地，只提取当前目标的顶层字段与指定分 P；不要把其他合集条目当作目标。 |
| curl 报 `Failed to connect to 127.0.0.1:<port>` | 同一请求在允许联网的执行环境中成功，说明原环境无法访问现有代理。不把它判成 B 站限制，不复制旧端口、不改全局代理；需要时走环境提供的正常联网授权。 |
| 请求 `qn=64`，实际只返回 480p / 360p | 使用实际提供的轨道。本次选择 H.264 480p，ffprobe 确认为 852 × 480。不要靠改请求参数宣称取得更高画质。 |
| 下载得到独立视频和音频 | 两个媒体文件分别核对，显式映射合并。只下载视频轨会无声。 |
| `subtitle.subtitles` 为 `[]` | 公开字幕不可用；提取完整音频转写，再用实际看过的嵌入字幕校正。空字幕不是下载或转写失败。 |
| 默认 Python 查不到 `mlx_whisper` | 本机已有兼容环境和模型缓存。检查实际解释器、包与模型位置，复用兼容环境；不先在默认环境反复安装。 |
| 已有 MLX，但报 `No Metal device available` | 本次是受限执行环境无法访问 GPU；在获得正常执行授权后 Metal 可用。先区分包缺失、设备缺失与环境权限，再决定是否回退 CPU。 |
| ASR 误写人名、英文工具名、游戏名和术语 | 完整帧中的嵌入字幕用于校正，例如 Trancy、罪恶都市、主观能动性、load 和 save。原始 ASR 不覆盖；无依据的词保留不确定标记。 |

只有错误条件确实改变后才重试。同一公开接口仍受登录、私密、删除、付费或验证码限制时，使用已有授权浏览器 / 本地材料；不反复碰同一失败请求，不把接口路径当作绕过访问限制的方法。

## 后续读取与实测范围

下载完成后按 [音频转写](transcription.md) 和 [视频分析格式](video-analysis.md) 继续。默认长视频每 3 秒采样；要真正打开联系表和关键单帧，不能把文件生成当作画面理解。校正完整逐字稿，线索放回对应时间段。

2026-10-12，macOS Apple Silicon，实测目标 [BV1LmvzB4EFp](https://www.bilibili.com/video/BV1LmvzB4EFp/)：

- 公开信息核对成功：上传者“极客Cut”，标题是云飞如何学习英语，目标 CID 为 35027553948。
- 页面时长 442 秒；H.264 视频与 AAC 音频分轨下载并合并后，实际时长 441.203 秒，852 × 480。
- 公开字幕为空；完整音频通过已有 MLX / Metal 环境转写，保留 184 段原始 ASR。
- 每 3 秒抽取 148 张完整帧；实际打开 17 张全程联系表、25 张采样单帧和 20 张补充单帧。没有连续完整播放视频。
- 原始音视频、签名 URL、ASR、截图与分析文档留在使用项目，不随 Skill 仓库发布。

上述在线获取是本次会话的实测结果；新增脚本的验证范围另见 [README](../README.md)。分 P、未来接口结构、需要登录的内容和更高画质不能由单条公开视频的结果推断。

