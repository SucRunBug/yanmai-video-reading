#!/usr/bin/env python3
"""Download observed Douyin media URLs and merge split video/audio tracks."""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from video_common import (
    allowed_https, duration, fresh_dir, has_stream, probe, run, save_json, tool,
)


def validate_request(config):
    page = allowed_https(config["page_url"], ("douyin.com",))
    if not re.fullmatch(r"/video/\d+/?", urlsplit(page).path):
        raise ValueError("page_url 必须是已核对的抖音视频页面")
    ua = config["user_agent"]
    if not isinstance(ua, str) or not ua.strip() or any(ord(c) < 32 for c in ua):
        raise ValueError("User-Agent 无效")
    for key in ("video_url", "audio_url"):
        if config.get(key):
            allowed_https(config[key], ("douyinvod.com",))
    if not config.get("video_url"):
        raise ValueError("缺少本次实际观察到的 video_url")
    return page, ua


def curl_download(url, path, page, ua, timeout):
    partial = path.with_suffix(".part")
    # Keep expiring URLs out of command arguments and shell history.
    config = "url = " + json.dumps(url, ensure_ascii=True) + "\n"
    try:
        result = subprocess.run([
            tool("curl"), "--config", "-", "--fail", "--location",
            "--max-redirs", "3", "--proto", "=https", "--proto-redir", "=https",
            "--silent", "--show-error", "--max-time", str(timeout),
            "--user-agent", ua, "--referer", page, "--output", str(partial),
        ], input=config, capture_output=True, text=True)
        if result.returncode:
            raise ValueError(
                "媒体下载失败，curl 退出码 %d；核对当前网络权限、UA / Referer 或重新取媒体地址"
                % result.returncode
            )
        if not partial.exists() or partial.stat().st_size == 0:
            raise ValueError("媒体响应为空")
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def download(config, output, ffmpeg="ffmpeg", ffprobe="ffprobe", timeout=60):
    page, ua = validate_request(config)
    tool("curl")
    tool(ffmpeg)
    tool(ffprobe)
    out = fresh_dir(output)
    video = out / "video_track.mp4"
    curl_download(config["video_url"], video, page, ua, timeout)
    video_info = probe(video, ffprobe)
    if not has_stream(video_info, "video"):
        raise ValueError("video_url 返回的文件没有视频轨")
    video_duration = duration(video_info)
    if config.get("audio_url"):
        audio = out / "audio_track.m4a"
        curl_download(config["audio_url"], audio, page, ua, timeout)
        audio_info = probe(audio, ffprobe)
        if not has_stream(audio_info, "audio"):
            raise ValueError("audio_url 返回的文件没有音频轨")
        audio_duration = duration(audio_info)
        if abs(video_duration - audio_duration) > max(2, video_duration * 0.05):
            raise ValueError("音视频时长明显不同，请重新核对两个地址是否属于同一目标")
        run([
            tool(ffmpeg), "-v", "error", "-n", "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", str(out / "video.mp4"),
        ])
    else:
        shutil.copyfile(video, out / "video.mp4")
    info = probe(out / "video.mp4", ffprobe)
    if not has_stream(info, "video"):
        raise ValueError("最终媒体没有视频轨")
    save_json(out / "source.json", {
        "platform": "douyin", "page_url": page,
        "content_id": urlsplit(page).path.strip("/").split("/")[-1],
        "media": info, "has_audio": has_stream(info, "audio"),
        "reading_status": "downloaded_not_read",
    })
    return out / "video.mp4"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="本地 JSON，含当前媒体 URL 与请求条件")
    parser.add_argument("--output", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if not (0 < args.timeout <= 600):
        parser.error("--timeout 必须在 0~600 秒之间")
    try:
        config = json.loads(Path(args.request).read_text(encoding="utf-8"))
        print(download(config, args.output, args.ffmpeg, args.ffprobe, args.timeout))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print("下载未完成：" + str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
