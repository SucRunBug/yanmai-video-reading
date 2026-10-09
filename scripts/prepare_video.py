#!/usr/bin/env python3
"""Inspect local video; create uncropped frames, contact sheets and optional audio."""

import argparse
import math
import re
import sys
from pathlib import Path

from video_common import duration, fresh_dir, has_stream, probe, run, save_json, tool

PTS = re.compile(r"\bn:\s*(\d+)\s+pts:\s*\S+\s+pts_time:\s*([\d.eE+\-]+)")


def extract_times(stderr):
    result = {}
    for match in PTS.finditer(stderr):
        result.setdefault(int(match.group(1)), float(match.group(2)))
    return result


def prepare(video, output, interval=None, at=(), audio=False,
            ffmpeg="ffmpeg", ffprobe="ffprobe"):
    video = Path(video).resolve(strict=True)
    info = probe(video, ffprobe)
    if not has_stream(info, "video"):
        raise ValueError("输入没有视频轨，不能进行画面读取")
    length = duration(info)
    interval = interval if interval is not None else (1 if length <= 120 else 3)
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("抽帧间隔必须为有限正数")
    if any(not math.isfinite(t) or t < 0 or t >= length for t in at):
        raise ValueError("--at 时间点必须在 [0, 实际时长) 范围内")
    if audio and not has_stream(info, "audio"):
        raise ValueError("输入没有音频轨；请确认是否还需合并独立音轨")
    ffmpeg = tool(ffmpeg)
    out = fresh_dir(output)
    frames = out / "frames"
    sheets = out / "sheets"
    frames.mkdir()
    sheets.mkdir()
    # Select actual source frames, then read their PTS from showinfo.
    # Unlike fps resampling, these timestamps do not imply synthesized timing.
    selected = "select='isnan(prev_selected_t)+gte(t-prev_selected_t,%.9f)',showinfo" % interval
    result = run([
        ffmpeg, "-hide_banner", "-n", "-i", str(video), "-map", "0:v:0",
        "-an", "-vf", selected, "-vsync", "vfr", "-q:v", "2",
        str(frames / "frame_%05d.jpg"),
    ])
    timestamps = extract_times(result.stderr)
    paths = sorted(frames.glob("frame_*.jpg"))
    if not paths:
        raise ValueError("没有生成画面")
    sampled = [{
        "file": path.relative_to(out).as_posix(),
        "timestamp_seconds": timestamps.get(index),
    } for index, path in enumerate(paths)]
    if any(item["timestamp_seconds"] is None for item in sampled):
        raise ValueError("无法对应抽帧时间戳，请检查当前 FFmpeg showinfo 输出")
    run([
        ffmpeg, "-v", "error", "-n", "-framerate", "1", "-i",
        str(frames / "frame_%05d.jpg"), "-vf",
        "scale=240:240:force_original_aspect_ratio=decrease,"
        "pad=240:240:(ow-iw)/2:(oh-ih)/2,tile=3x3", "-vsync", "vfr",
        "-q:v", "2", str(sheets / "sheet_%03d.jpg"),
    ])
    details = []
    for index, timestamp in enumerate(at, 1):
        target = out / ("detail_%03d.jpg" % index)
        result = run([
            ffmpeg, "-hide_banner", "-n", "-i", str(video), "-an",
            "-vf", "select='gte(t,%.9f)',showinfo" % timestamp,
            "-frames:v", "1", "-vsync", "vfr", "-q:v", "2", str(target),
        ])
        actual = extract_times(result.stderr).get(0)
        if not target.exists() or actual is None:
            raise ValueError("指定时间没有可用画面：" + str(timestamp))
        details.append({"file": target.name, "requested_seconds": timestamp,
                        "timestamp_seconds": actual})
    if audio:
        run([
            ffmpeg, "-v", "error", "-n", "-i", str(video), "-map", "0:a:0",
            "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out / "audio.wav"),
        ])
    sheet_records = [{
        "file": path.relative_to(out).as_posix(),
        "frames_in_row_major_order": [item["file"] for item in sampled[i * 9:(i + 1) * 9]],
    } for i, path in enumerate(sorted(sheets.glob("sheet_*.jpg")))]
    save_json(out / "media.json", {
        "input_file": str(video), "media": info, "duration_seconds": length,
        "interval_seconds": interval, "frames": sampled, "sheets": sheet_records,
        "detail_frames": details, "audio_file": "audio.wav" if audio else None,
        "recognition_performed": False,
        "reading_scope": "Images generated; open images and/or transcribe audio before reporting content.",
    })
    return out / "media.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--output", required=True)
    parser.add_argument("--interval", type=float)
    parser.add_argument("--at", nargs="+", type=float, default=[])
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    try:
        print(prepare(args.video, args.output, args.interval, args.at, args.audio,
                      args.ffmpeg, args.ffprobe))
    except (ValueError, OSError) as error:
        print("抽帧未完成：" + str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
