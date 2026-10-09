# 小红书：公开手机分享页路径

方法参考 [SucRunBug/home-food 的 video-reading.md](https://github.com/SucRunBug/home-food/blob/78f7c7ae0c840b21fd43d207dca60266ceadaaa6/references/video-reading.md)。这里把其菜谱读取流程整理成通用视频读取方法；脚本为本仓库实现，不要求安装 home-food。

## 首选路径

1. 展开用户给的短链接。若桌面页面跳到登录页，检查 `redirectPath` 是否指向原笔记，保留分享参数，核对 `/explore/<id>` 或 `/discovery/item/<id>` 的笔记 ID。
2. 使用 HTTPS 和手机 Safari User-Agent 请求同一笔记的公开分享页。
3. 从页面内 `window.__SETUP_SERVER_STATE__` 解码数据；常见视频字段为 `LAUNCHER_SSR_STORE_PAGE_DATA.noteData.video.media.stream.h264[0].masterUrl`。也可检查当前页面的 `__INITIAL_STATE__`。
4. 按目标 ID 匹配笔记，再选择当前笔记内的 HTTPS `*.xhscdn.com` 媒体 URL，H.264 优先。不要执行网页 JavaScript；数据中的 `undefined` 只在字符串外转换为 `null`。
5. 带手机 User-Agent 和小红书 Referer 下载。确认响应为媒体，并用 ffprobe 核对视频轨和时长。

```bash
python3 scripts/fetch_xhs_video.py 'USER_SHARE_URL' --output sources/target
python3 scripts/prepare_video.py sources/target/video.mp4 --output output/target
```

下载脚本使用 Python 标准库。它会保留本地页面、匹配笔记数据、元信息与视频；页面和媒体 URL 可能含临时参数，均不可直接公开。输出目录必须新建或为空。

短链接未能提供可确认 ID 时，只有页面数据中唯一视频笔记可以继续；若有多个候选，停止并用同一页面核对，不能随便取第一个。已知目标 ID 与页面数据不一致时拒绝继续。

## 画面与音频

先打开联系表，再看完整帧。保留顶部、底部字幕和操作区域。数量、时间、产品名、操作顺序需要对应具体帧；默认抽帧间隔不等于完整视觉覆盖。错过快速字幕时补用 `--interval 0.5` 或 `--at`。

需要讲解时提取音频，再按 [transcription.md](transcription.md) 转写。只生成图片不能称为看过视频，只提取音频不能称为完成转写。

## 失败换路与停止条件

- 桌面登录页：先试原笔记的公开手机页；这只是访问同一公开内容，不绕过账号权限。
- 没有目标数据：保留 ID 与错误分类，用当前浏览器打开同一目标，确认是否公开及页面结构是否变化。
- 403 / 签名过期 / 返回 HTML：重新读取原分享页，取得当前媒体地址；不要长期复用旧地址。
- 当前浏览器能播放但解析失败：用其实际媒体请求作为备用，再检查媒体与抽帧。
- 登录、私密、删除、验证码或持续结构变化：停止重复请求，说明实际限制，使用用户提供的本地视频或已有文案。

脚本每次最多请求三个同目标页面、尝试三个同目标媒体候选；失败后应按失败层处理，而不是循环再跑同一命令。通用错误处理见 [troubleshooting.md](troubleshooting.md)。

## 来源中的验证实例

上游文档记录了“肥牛滑蛋”示例：笔记 ID `67f4e33e000000001b025337`，约 42.18 秒、720 × 1280。上游当时依靠画面与字幕读取，没有做音频转写。这个实例说明方法曾成功，不保证链接一直有效或字段一直不变；不要将实例时长、ID 当作通用参数。
