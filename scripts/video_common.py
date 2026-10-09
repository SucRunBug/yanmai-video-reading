"""Shared local media utilities; Python 3.9+, no third-party packages."""

import json
import math
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def tool(name):
    found = shutil.which(name)
    if not found:
        raise ValueError("找不到媒体工具：" + name)
    return found


def run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        # Local media commands only. Network stderr must be handled separately.
        raise ValueError("媒体处理失败：" + result.stderr[-2000:])
    return result


def probe(path, ffprobe="ffprobe"):
    result = run([
        tool(ffprobe), "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path),
    ])
    return json.loads(result.stdout)


def duration(info):
    value = float(info.get("format", {}).get("duration", 0))
    if not math.isfinite(value) or value <= 0:
        raise ValueError("媒体时长无效")
    return value


def has_stream(info, kind):
    return any(s.get("codec_type") == kind for s in info.get("streams", []))


def fresh_dir(path):
    path = Path(path)
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError("输出目录已含文件，请指定新的目录：" + str(path))
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def allowed_https(url, domains, upgrade=False):
    """Validate a URL without logging signed queries or accepting suffix lookalikes."""
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("地址含非法空白或控制字符")
    parsed = urlsplit(url)
    if upgrade and parsed.scheme == "http":
        parsed = parsed._replace(scheme="https")
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or not any(host == d or host.endswith("." + d) for d in domains)):
        raise ValueError("地址不是允许的 HTTPS 平台域名")
    return parsed.geturl()
