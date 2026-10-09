#!/usr/bin/env python3
"""Read an identified public XHS mobile page and download its current video."""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from video_common import allowed_https, duration, fresh_dir, has_stream, probe, save_json, tool

PAGE_DOMAINS = ("xiaohongshu.com", "xhslink.com", "xhslink.cn")
MEDIA_DOMAINS = ("xhscdn.com",)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
    "Mobile/15E148 Safari/604.1"
)
STATE_ASSIGNMENT = re.compile(
    r"(?:window\.)?__(?:SETUP_SERVER_STATE|INITIAL_STATE)__\s*=\s*"
)
NOTE_ID = re.compile(r"/(?:explore|discovery/item)/([0-9a-fA-F]{24})(?:/|$)")


def normalize_page(url):
    url = allowed_https(url, PAGE_DOMAINS, upgrade=True)
    for _ in range(3):
        redirect = parse_qs(urlsplit(url).query).get("redirectPath", [])
        if not redirect:
            break
        url = allowed_https(urljoin(url, redirect[0]), PAGE_DOMAINS, upgrade=True)
    return url


def note_id(url):
    match = NOTE_ID.search(urlsplit(normalize_page(url)).path)
    return match.group(1).lower() if match else None


def json_undefined(text):
    """Replace JS undefined literals, preserving strings and escaped quotes."""
    output = []
    quoted = escaped = False
    i = 0
    while i < len(text):
        char = text[i]
        if quoted:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            i += 1
            continue
        if char == '"':
            quoted = True
        if (text.startswith("undefined", i)
                and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_"))
                and (i + 9 == len(text) or not
                     (text[i + 9].isalnum() or text[i + 9] == "_"))):
            output.append("null")
            i += 9
        else:
            output.append(char)
            i += 1
    return "".join(output)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def media_urls(note):
    video = note.get("video", {})
    if not isinstance(video, dict):
        return []
    media = video.get("media", {})
    if not isinstance(media, dict):
        return []
    streams = media.get("stream", {})
    if not isinstance(streams, dict):
        return []
    keys = [k for k in ("h264", "h265", "av1", "h266") if k in streams]
    keys += [k for k in streams if k not in keys]
    found = []
    for key in keys:
        entries = streams[key]
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            urls = [entry.get("masterUrl")]
            backups = entry.get("backupUrls", entry.get("backupUrl", []))
            urls += backups if isinstance(backups, list) else [backups]
            for url in urls:
                if not isinstance(url, str):
                    continue
                try:
                    url = allowed_https(url, MEDIA_DOMAINS, upgrade=True)
                except ValueError:
                    continue
                if url not in found:
                    found.append(url)
    return found


def parse_note(html, expected=None):
    candidates = {}
    for match in STATE_ASSIGNMENT.finditer(html):
        try:
            state, _ = json.JSONDecoder().raw_decode(
                json_undefined(html[match.end():]).lstrip()
            )
        except (ValueError, RecursionError):
            continue
        for item in walk(state):
            ident = item.get("noteId", item.get("note_id", ""))
            if (isinstance(ident, str) and re.fullmatch(r"[0-9a-fA-F]{24}", ident)
                    and media_urls(item)):
                candidates[ident.lower()] = item
    if expected:
        if expected.lower() not in candidates:
            raise ValueError("页面没有匹配目标 ID 的视频笔记")
        return candidates[expected.lower()]
    if len(candidates) != 1:
        raise ValueError("页面目标不唯一或没有视频笔记，需先确认内容 ID")
    return next(iter(candidates.values()))


class PlatformRedirects(HTTPRedirectHandler):
    def __init__(self, domains):
        self.domains = domains

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = allowed_https(newurl, self.domains, upgrade=True)
        return super().redirect_request(req, fp, code, msg, headers, url)


def request(url, domains, timeout):
    opener = build_opener(PlatformRedirects(domains))
    return opener.open(Request(url, headers={
        "User-Agent": MOBILE_UA, "Referer": "https://www.xiaohongshu.com/",
    }), timeout=timeout)


def download(url, target, timeout):
    partial = target.with_suffix(".part")
    try:
        with request(url, MEDIA_DOMAINS, timeout) as response:
            head = response.read(64)
            if head[4:8] != b"ftyp":
                raise ValueError("媒体响应不是 MP4，可能是错误页或地址过期")
            with partial.open("wb") as output:
                output.write(head)
                shutil.copyfileobj(response, output, length=1024 * 1024)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def error_kind(error):
    if isinstance(error, HTTPError):
        return "HTTP " + str(error.code)
    if isinstance(error, URLError):
        # Avoid exposing signed URLs while retaining a useful failure category.
        return "网络 / 代理 / TLS 请求失败（" + type(error.reason).__name__ + "）"
    if isinstance(error, (TimeoutError, OSError)):
        return "连接超时或本地 IO 失败"
    return str(error)


def fetch(url, output, timeout=30, ffprobe="ffprobe"):
    current = normalize_page(url)
    expected = note_id(current)
    tool(ffprobe)
    out = fresh_dir(output)
    tried = set()
    note = None
    last_error = "没有页面数据"
    for attempt in range(1, 4):
        if current in tried:
            break
        tried.add(current)
        try:
            with request(current, PAGE_DOMAINS, timeout) as response:
                final = allowed_https(response.geturl(), PAGE_DOMAINS, upgrade=True)
                raw = response.read(5 * 1024 * 1024 + 1)
                if len(raw) > 5 * 1024 * 1024:
                    raise ValueError("页面超过解析大小限制")
            html = raw.decode("utf-8", errors="replace")
            (out / ("page-%d.html" % attempt)).write_text(html, encoding="utf-8")
            resolved = normalize_page(final)
            resolved_id = note_id(resolved)
            if expected and resolved_id and expected != resolved_id:
                raise ValueError("跳转到了不同笔记 ID，停止读取")
            expected = expected or resolved_id
            try:
                note = parse_note(html, expected)
                current = resolved
                break
            except ValueError as error:
                last_error = error_kind(error)
            if resolved not in tried:
                current = resolved
            elif "/explore/" in resolved:
                current = resolved.replace("/explore/", "/discovery/item/", 1)
            else:
                break
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            last_error = error_kind(error)
            break  # An unchanged network request is not a new reading path.
    if note is None:
        raise ValueError(last_error)
    save_json(out / "note-data.json", note)
    for candidate in media_urls(note)[:3]:
        try:
            download(candidate, out / "video.mp4", timeout)
            info = probe(out / "video.mp4", ffprobe)
            if not has_stream(info, "video"):
                raise ValueError("下载媒体没有视频轨")
            duration(info)
            save_json(out / "source.json", {
                "platform": "xiaohongshu", "share_url": url,
                "resolved_page_url": current,
                "note_id": note.get("noteId", note.get("note_id")),
                "title": note.get("title"), "author": note.get("user"),
                "media": info, "reading_status": "downloaded_not_read",
            })
            return out / "video.mp4"
        except (ValueError, HTTPError, URLError, TimeoutError, OSError) as error:
            last_error = error_kind(error)
            (out / "video.mp4").unlink(missing_ok=True)
    raise ValueError("同目标媒体候选均失败：" + last_error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(json.dumps({"python": sys.version.split()[0],
                          "ffmpeg": bool(shutil.which("ffmpeg")),
                          "ffprobe": bool(shutil.which(args.ffprobe))}))
        return
    if not args.url or not args.output or not (0 < args.timeout <= 300):
        parser.error("需要 url、--output 和 0~300 秒之间的 --timeout")
    try:
        print(fetch(args.url, args.output, args.timeout, args.ffprobe))
    except (ValueError, OSError) as error:
        print("读取未完成：" + error_kind(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
