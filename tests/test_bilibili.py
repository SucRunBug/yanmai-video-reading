"""Offline Bilibili tests: identity, returned formats, split tracks and failures."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fetch_bilibili_video import (
    api_data, curl_fetch, fetch, parse_target, public_subtitles, select_page,
    select_streams, stream_urls,
)
from video_common import duration, has_stream, probe

BV = "BV0000000001"
OTHER_BV = "BV0000000002"


def streams():
    return {"quality": 64, "dash": {
        "video": [
            {"id": 32, "codecid": 12, "width": 852, "height": 480,
             "base_url": "https://media.bilivideo.com/hevc?signature=TEST_ONLY"},
            {"id": 32, "codecid": 7, "width": 852, "height": 480,
             "baseUrl": "https://media.bilivideo.com/video?signature=TEST_ONLY"},
            {"id": 16, "codecid": 7, "width": 640, "height": 360,
             "baseUrl": "https://media.bilivideo.com/low?signature=TEST_ONLY"},
        ],
        "audio": [
            {"id": 30216, "bandwidth": 64000,
             "baseUrl": "https://media.bilivideo.cn/low-audio?signature=TEST_ONLY"},
            {"id": 30280, "bandwidth": 192000,
             "baseUrl": "https://media.bilivideo.com/audio?signature=TEST_ONLY"},
        ],
    }}


class BilibiliIdentityTests(unittest.TestCase):
    def test_bv_tracking_and_selected_part(self):
        self.assertEqual(parse_target(BV), (BV, 1))
        self.assertEqual(parse_target(
            "https://www.bilibili.com/video/" + BV + "/?p=2&vd_source=TEST"),
            (BV, 2))
        self.assertEqual(parse_target("https://www.bilibili.com/video/" + BV + "/?p=2", 3),
                         (BV, 3))
        for value in ("https://bilibili.com.evil.example/video/" + BV,
                      "https://www.bilibili.com/video/" + BV + "/?p=0",
                      "https://www.bilibili.com/video/" + BV + "/?p=x",
                      "https://www.bilibili.com/video/" + BV + "/?p=1&p=2",
                      "https://www.bilibili.com/", "https://b23.tv/unknown"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_target(value)

    def test_selects_requested_cid_without_using_collection(self):
        data = {"bvid": BV, "pages": [{"page": 1, "cid": 101}, {"page": 2, "cid": 202}],
                "ugc_season": {"episodes": [{"bvid": OTHER_BV, "cid": 999}]}}
        self.assertEqual(select_page(data, BV, 2)["cid"], 202)
        with self.assertRaises(ValueError):
            select_page(data, OTHER_BV, 1)
        with self.assertRaises(ValueError):
            select_page(data, BV, 3)
        data["pages"].append({"page": 2, "cid": 303})
        with self.assertRaises(ValueError):
            select_page(data, BV, 2)

    def test_actual_formats_h264_priority_and_audio_bandwidth(self):
        video, audio = select_streams(streams())
        self.assertEqual((video["id"], video["codecid"], video["height"]), (32, 7, 480))
        self.assertEqual(audio["id"], 30280)
        with self.assertRaises(ValueError):
            select_streams({"dash": {"video": [video], "audio": []}})
        with self.assertRaises(ValueError):
            select_streams({"durl": [{"url": "https://media.bilivideo.com/other"}]})

    def test_media_domains_and_snake_case_backup(self):
        urls = stream_urls({
            "base_url": "http://media.bilivideo.com/video",
            "backup_url": ["https://media.bilivideo.cn/backup",
                           "https://bilivideo.com.evil.example/video",
                           "https://user:password@media.bilivideo.com/video"],
        })
        self.assertEqual(urls, ["https://media.bilivideo.com/video",
                                "https://media.bilivideo.cn/backup"])

    def test_subtitle_empty_available_and_api_failure_are_distinct(self):
        self.assertEqual(public_subtitles({"subtitle": {"subtitles": []}})["status"], "empty")
        actual = public_subtitles({"subtitle": {"subtitles": [{"lan": "zh-CN"}]}})
        self.assertEqual((actual["status"], actual["languages"]), ("available", ["zh-CN"]))
        with self.assertRaises(ValueError):
            api_data({"code": -101, "data": {}})
        with self.assertRaises(ValueError):
            api_data({"code": 0, "data": None})


class BilibiliRequestTests(unittest.TestCase):
    def test_signed_url_not_in_arguments_and_failure_does_not_expose_it(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "video.m4s"
            def fail(args, **kwargs):
                self.assertNotIn("signature=SECRET", " ".join(args))
                self.assertIn("signature=SECRET", kwargs["input"])
                self.assertIn("--referer", args)
                self.assertIn("--user-agent", args)
                target.with_name(target.name + ".part").write_bytes(b"partial")
                return subprocess.CompletedProcess(args, 7, "", "signature=SECRET")
            with patch("fetch_bilibili_video.subprocess.run", side_effect=fail):
                with self.assertRaises(ValueError) as caught:
                    curl_fetch("https://media.bilivideo.com/video?signature=SECRET",
                               target, "https://www.bilibili.com/video/" + BV + "/", "Test", 30)
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name(target.name + ".part").exists())


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg / ffprobe required")
class BilibiliPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="bilibili-reading-tests-")
        cls.root = Path(cls.temp.name)
        cls.media = cls.root / "synthetic.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=160x120:rate=10:duration=1.4",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.4",
            "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(cls.media),
        ], check=True)
        cls.video, cls.audio = cls.root / "video.mp4", cls.root / "audio.m4a"
        for target, flag in ((cls.video, "-an"), (cls.audio, "-vn")):
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(cls.media), flag,
                            "-c", "copy", str(target)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_pipeline(self, name, subtitle_failure=False):
        seen = []
        def fake_api(path, endpoint, params, *args):
            seen.append((endpoint, params))
            self.assertEqual(params["bvid"], BV)
            if endpoint == "x/web-interface/view":
                data = {"bvid": BV, "aid": 1, "title": "Synthetic test", "owner": {"name": "Test"},
                        "pubdate": 0, "duration": 2, "pages": [
                            {"page": 1, "cid": 101, "duration": 2, "part": "First"},
                            {"page": 2, "cid": 202, "duration": 2, "part": "Selected"}]}
            elif endpoint == "x/player/playurl":
                self.assertEqual(params["cid"], 202)
                data = streams()
            else:
                self.assertEqual(params["cid"], 202)
                if subtitle_failure:
                    raise ValueError("Synthetic subtitle API failure")
                data = {"subtitle": {"subtitles": []}}
            path.write_text(json.dumps({"code": 0, "data": data}))
            return data

        def fake_download(url, target, *args):
            path = urlsplit(url).path
            shutil.copyfile(self.audio if path == "/audio" else self.video, target)

        with patch("fetch_bilibili_video.read_api", side_effect=fake_api), \
                patch("fetch_bilibili_video.curl_fetch", side_effect=fake_download):
            result = fetch("https://www.bilibili.com/video/" + BV + "/?p=2", self.root / name)
        return result, seen

    def test_full_pipeline_merges_correct_part_and_preserves_metadata(self):
        result, seen = self.run_pipeline("success")
        info = probe(result)
        self.assertTrue(has_stream(info, "video"))
        self.assertTrue(has_stream(info, "audio"))
        self.assertAlmostEqual(duration(info), duration(probe(self.media)), places=2)
        raw = (result.parent / "source.json").read_text()
        self.assertNotIn("signature=", raw)
        metadata = json.loads(raw)
        self.assertEqual((metadata["bvid"], metadata["cid"], metadata["page"]), (BV, 202, 2))
        self.assertEqual(metadata["requested_qn"], 64)
        self.assertEqual(metadata["selected_video"]["id"], 32)
        self.assertEqual(metadata["public_subtitles"]["status"], "empty")
        self.assertEqual(metadata["reading_status"], "downloaded_not_read")
        self.assertEqual(len(seen), 3)

    def test_subtitle_api_failure_keeps_completed_media(self):
        result, _ = self.run_pipeline("subtitle-failure", subtitle_failure=True)
        metadata = json.loads((result.parent / "source.json").read_text())
        self.assertEqual(metadata["public_subtitles"]["status"], "unavailable")
        self.assertTrue(has_stream(probe(result), "audio"))

    def test_existing_output_is_preserved_before_network_requests(self):
        out = self.root / "already-read"
        out.mkdir()
        (out / "source.json").write_text("preserve")
        with patch("fetch_bilibili_video.read_api") as api:
            with self.assertRaises(ValueError):
                fetch(BV, out)
            api.assert_not_called()
        self.assertEqual((out / "source.json").read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()

