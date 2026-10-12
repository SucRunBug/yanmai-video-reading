#!/usr/bin/env python3
"""Download a verified public Bilibili BV video through its current DASH URLs."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import parse_qs, urlencode, urlsplit

from video_common import (
    allowed_https, duration, fresh_dir, has_stream, probe, run, save_json, tool,
)

BV_ID = re.compile(r"BV[0-9A-Za-z]{10}")
MEDIA_DOMAINS = ("bilivideo.com", "bilivideo.cn", "hdslb.com")
USER_AGENT = "Mozilla/5.0"


def parse_target(value, page=None):
    """Retain one BV identity; tracking queries do not select a different video."""
    value = value.strip()
    selected = 1
    if BV_ID.fullmatch(value):
        bvid = value
    else:
        url = allowed_https(value, ("bilibili.com",), upgrade=True)
        parsed = urlsplit(url)
        match = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10})/?", parsed.path)
        if not match:
            raise ValueError("需要完整的 B 站 /video/BV… 链接或 BV 号；短链接先解析并核对")
        bvid = match.group(1)
        query_pages = parse_qs(parsed.query).get("p", [])
        if query_pages:
            if len(query_pages) != 1:
                raise ValueError("链接中的分 P 参数不唯一")
            try:
                selected = int(query_pages[0])
            except ValueError:
                raise ValueError("链接中的分 P 参数无效") from None
    if page is not None:
        selected = page
    if selected < 1:
        raise ValueError("分 P 编号必须从 1 开始")
    return bvid, selected


def api_data(payload):
    if not isinstance(payload, dict) or payload.get("code") != 0:
        code = payload.get("code", "unknown") if isinstance(payload, dict) else "invalid"
        raise ValueError("B 站公开接口未返回成功数据（code=%s）；核对访问条件或接口变化" % code)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("B 站公开接口缺少 data 对象")
    return data


def select_page(data, bvid, page_number):
    if data.get("bvid") != bvid:
        raise ValueError("返回的 BV 号与目标不符，停止读取")
    pages = data.get("pages")
    if not isinstance(pages, list):
        raise ValueError("视频信息没有分 P 列表")
    matches = [p for p in pages if isinstance(p, dict) and p.get("page") == page_number]
    if len(matches) != 1:
        raise ValueError("未找到唯一的目标分 P；不能改取推荐视频或其他分 P")
    page = matches[0]
    if not isinstance(page.get("cid"), int) or page["cid"] <= 0:
        raise ValueError("目标分 P 缺少有效 CID")
    return page


def stream_urls(stream):
    urls = []
    primary = stream.get("baseUrl") or stream.get("base_url")
    backups = stream.get("backupUrl", stream.get("backup_url", []))
    values = [primary] + (backups if isinstance(backups, list) else [backups])
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            url = allowed_https(value, MEDIA_DOMAINS, upgrade=True)
        except ValueError:
            continue
        if url not in urls:
            urls.append(url)
    return urls


def select_streams(data):
    dash = data.get("dash")
    if not isinstance(dash, dict):
        raise ValueError("当前响应没有 DASH；本脚本不猜测其他格式，改用同一目标的浏览器媒体请求")
    videos = [v for v in dash.get("video", []) if isinstance(v, dict) and stream_urls(v)]
    audios = [a for a in dash.get("audio", []) if isinstance(a, dict) and stream_urls(a)]
    if not videos or not audios:
        raise ValueError("没有公开可用的 DASH 音视频轨；检查访问条件，不能把静音视频当完整素材")
    # H.264 first for local compatibility. Only choose formats actually returned.
    compatible = [v for v in videos if v.get("codecid") == 7] or videos
    video = max(compatible, key=lambda v: (v.get("height", 0), v.get("width", 0),
                                          v.get("bandwidth", 0)))
    audio = max(audios, key=lambda a: (a.get("bandwidth", 0), a.get("id", 0)))
    return video, audio


def curl_fetch(url, target, page_url, user_agent, timeout):
    partial = target.with_name(target.name + ".part")
    # Do not expose signed media URLs in command arguments or failure output.
    config = "url = " + json.dumps(url, ensure_ascii=True) + "\n"
    try:
        result = subprocess.run([
            tool("curl"), "--config", "-", "--fail", "--location",
            "--max-redirs", "3", "--proto", "=https", "--proto-redir", "=https",
            "--silent", "--show-error", "--connect-timeout", "15",
            "--max-time", str(timeout), "--user-agent", user_agent,
            "--referer", page_url, "--output", str(partial),
        ], input=config, capture_output=True, text=True)
        if result.returncode:
            raise ValueError(
                "请求失败，curl 退出码 %d；先检查网络权限、代理、UA / Referer，"
                "或重新获取同一目标的媒体地址" % result.returncode
            )
        if not partial.exists() or not partial.stat().st_size:
            raise ValueError("响应为空")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def read_api(path, endpoint, params, page_url, user_agent, timeout):
    url = "https://api.bilibili.com/" + endpoint + "?" + urlencode(params)
    curl_fetch(url, path, page_url, user_agent, timeout)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("接口响应过大，停止解析")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("接口响应不是 JSON，可能是错误页或访问限制") from None
    return api_data(payload)


def download_stream(stream, path, kind, page_url, user_agent, timeout, ffprobe):
    last_error = "没有可用的媒体地址"
    for url in stream_urls(stream)[:2]:
        try:
            curl_fetch(url, path, page_url, user_agent, timeout)
            info = probe(path, ffprobe)
            if not has_stream(info, kind):
                raise ValueError("下载文件没有所需的 %s 轨" % kind)
            duration(info)
            return info
        except (ValueError, OSError) as error:
            last_error = str(error)
            path.unlink(missing_ok=True)
    raise ValueError("同目标 %s 轨下载未完成：%s" % (kind, last_error))


def public_subtitles(data):
    subtitle = data.get("subtitle") or {}
    if not isinstance(subtitle, dict) or not isinstance(subtitle.get("subtitles", []), list):
        raise ValueError("公开字幕响应结构变化")
    items = subtitle.get("subtitles", [])
    return {"status": "available" if items else "empty",
            "count": len(items),
            "languages": [s.get("lan") for s in items if isinstance(s, dict)]}


def fetch(value, output, page=None, timeout=120, ffmpeg="ffmpeg", ffprobe="ffprobe",
          user_agent=USER_AGENT):
    bvid, number = parse_target(value, page)
    if not user_agent.strip() or any(ord(c) < 32 for c in user_agent):
        raise ValueError("User-Agent 无效")
    for name in ("curl", ffmpeg, ffprobe):
        tool(name)
    out = fresh_dir(output)
    canonical = "https://www.bilibili.com/video/%s/" % bvid
    referer = canonical if number == 1 else canonical + "?p=%d" % number
    view = read_api(out / "view-api.json", "x/web-interface/view", {"bvid": bvid},
                    referer, user_agent, timeout)
    selected = select_page(view, bvid, number)
    cid = selected["cid"]
    info = {key: view.get(key) for key in
            ("bvid", "aid", "title", "owner", "pubdate", "duration")}
    info["selected_page"] = selected
    save_json(out / "video-info.json", info)
    play = read_api(out / "playurl-api.json", "x/player/playurl",
                    {"bvid": bvid, "cid": cid, "qn": 64, "fnval": 16, "fourk": 0},
                    referer, user_agent, timeout)
    video, audio = select_streams(play)
    video_path, audio_path = out / "video-track.m4s", out / "audio-track.m4s"
    vinfo = download_stream(video, video_path, "video", referer, user_agent, timeout, ffprobe)
    ainfo = download_stream(audio, audio_path, "audio", referer, user_agent, timeout, ffprobe)
    if abs(duration(vinfo) - duration(ainfo)) > max(2, duration(vinfo) * 0.05):
        raise ValueError("音视频时长明显不同，请核对是否属于同一 BV / CID")
    result = out / "video.mp4"
    run([tool(ffmpeg), "-v", "error", "-n", "-i", str(video_path), "-i", str(audio_path),
         "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", str(result)])
    media = probe(result, ffprobe)
    if not has_stream(media, "video") or not has_stream(media, "audio"):
        raise ValueError("最终文件缺少视频轨或音频轨")
    actual_duration = duration(media)
    # Subtitle metadata is optional; an empty or failed response is not a failed download.
    try:
        subtitle_data = read_api(out / "player-api.json", "x/player/v2",
                                 {"bvid": bvid, "cid": cid}, referer, user_agent, timeout)
        subtitles = public_subtitles(subtitle_data)
    except (ValueError, OSError) as error:
        subtitles = {"status": "unavailable", "count": None, "error": str(error)}
    published = view.get("pubdate")
    published_at = (datetime.fromtimestamp(published, timezone(timedelta(hours=8))).isoformat()
                    if isinstance(published, (int, float)) else None)
    save_json(out / "source.json", {
        "platform": "bilibili", "share_url": value, "canonical_url": referer,
        "bvid": bvid, "aid": view.get("aid"), "cid": cid, "page": number,
        "title": view.get("title"), "part": selected.get("part"), "owner": view.get("owner"),
        "published_at_china": published_at, "page_duration_seconds": selected.get("duration"),
        "actual_duration_seconds": actual_duration, "requested_qn": 64,
        "selected_video": {k: video.get(k) for k in ("id", "codecid", "width", "height")},
        "selected_audio": {k: audio.get(k) for k in ("id", "codecid", "bandwidth")},
        "public_subtitles": subtitles, "media": media, "has_audio": True,
        "reading_status": "downloaded_not_read",
    })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--page", type=int, help="Explicitly select a numbered part")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--user-agent", default=USER_AGENT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(json.dumps({"python": sys.version.split()[0],
                          "curl": bool(shutil.which("curl")),
                          "ffmpeg": bool(shutil.which(args.ffmpeg)),
                          "ffprobe": bool(shutil.which(args.ffprobe))}))
        return
    if not args.url or not args.output or not 0 < args.timeout <= 600:
        parser.error("需要 url、--output 和 0~600 秒之间的 --timeout")
    try:
        print(fetch(args.url, args.output, args.page, args.timeout,
                    args.ffmpeg, args.ffprobe, args.user_agent))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print("B 站读取未完成：" + str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

