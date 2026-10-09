"""Offline tests: target identity, URL boundaries and real media processing."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fetch_xhs_video import json_undefined, media_urls, normalize_page, note_id, parse_note
from download_douyin_media import download, validate_request
from prepare_video import prepare
from video_common import allowed_https, has_stream, probe

NOTE_A = "a" * 24
NOTE_B = "b" * 24


def note(ident, title="测试 undefined 字符串"):
    return {"noteId": ident, "title": title, "video": {"media": {"stream": {
        "h264": [{"masterUrl": "https://media.xhscdn.com/test.mp4"}],
    }}}}


def page(notes):
    return "<script>window.__SETUP_SERVER_STATE__=" + json.dumps(notes) + ";</script>"


class PageTests(unittest.TestCase):
    def test_expected_note_overrides_recommendations(self):
        selected = parse_note(page([note(NOTE_B, "推荐"), note(NOTE_A, "目标")]), NOTE_A)
        self.assertEqual(selected["title"], "目标")

    def test_mismatched_and_ambiguous_notes_fail(self):
        with self.assertRaises(ValueError):
            parse_note(page([note(NOTE_B)]), NOTE_A)
        with self.assertRaises(ValueError):
            parse_note(page([note(NOTE_A), note(NOTE_B)]))

    def test_undefined_does_not_change_title(self):
        source = '{"x":undefined,"title":"undefined and \\\"quoted\\\"","y":[undefined]}'
        decoded = json.loads(json_undefined(source))
        self.assertIsNone(decoded["x"])
        self.assertEqual(decoded["title"], 'undefined and "quoted"')
        self.assertEqual(decoded["y"], [None])

    def test_initial_state_and_single_shortlink_candidate(self):
        source = page([note(NOTE_A)]).replace("__SETUP_SERVER_STATE__", "__INITIAL_STATE__")
        self.assertEqual(parse_note(source)["noteId"], NOTE_A)

    def test_login_redirect_preserves_target_and_share_query(self):
        url = ("http://www.xiaohongshu.com/login?redirectPath="
               "%2Fexplore%2F" + NOTE_A + "%3Fxsec_token%3DTEST%26source%3Dshare")
        result = normalize_page(url)
        self.assertTrue(result.startswith("https://www.xiaohongshu.com/explore/"))
        self.assertIn("xsec_token=TEST&source=share", result)
        self.assertEqual(note_id(result), NOTE_A)

    def test_redirect_to_unrelated_host_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_page("https://www.xiaohongshu.com/login?redirectPath=https%3A%2F%2Fevil.example")

    def test_url_boundaries_and_credentials(self):
        allowed_https("https://v.example.douyinvod.com/media", ("douyinvod.com",))
        for url in ("https://douyinvod.com.evil.example/a", "https://evil-douyinvod.com/a",
                    "https://user:pass@a.douyinvod.com/a", "http://a.douyinvod.com/a",
                    "https://a.douyinvod.com:444/a", "file:///tmp/video.mp4"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                allowed_https(url, ("douyinvod.com",))

    def test_media_codec_priority_and_invalid_host(self):
        data = note(NOTE_A)
        data["video"]["media"]["stream"] = {
            "h265": [{"masterUrl": "https://media.xhscdn.com/hevc.mp4"}],
            "h264": [{"masterUrl": "http://media.xhscdn.com/avc.mp4",
                      "backupUrls": ["https://xhscdn.com.evil.example/bad.mp4"]}],
        }
        self.assertEqual(media_urls(data), ["https://media.xhscdn.com/avc.mp4",
                                            "https://media.xhscdn.com/hevc.mp4"])

    def test_douyin_request_requires_target_and_media(self):
        config = {"page_url": "https://www.douyin.com/video/123456",
                  "user_agent": "Test Browser", "video_url": "https://v.douyinvod.com/media"}
        validate_request(config)
        config["page_url"] = "https://www.douyin.com/"
        with self.assertRaises(ValueError):
            validate_request(config)

    def test_missing_media_and_url_control_characters_fail_cleanly(self):
        data = note(NOTE_A)
        data["video"]["media"] = None
        with self.assertRaises(ValueError):
            parse_note(page([data]), NOTE_A)
        with self.assertRaises(ValueError):
            allowed_https("https://v.douyinvod.com/media\n", ("douyinvod.com",))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg / ffprobe required")
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="video-reading-tests-")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "synthetic.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=160x120:rate=10:duration=2.4", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=2.4", "-c:v", "mpeg4",
            "-c:a", "aac", "-shortest", str(cls.source),
        ], check=True)
        cls.video = cls.root / "video-track.mp4"
        cls.audio = cls.root / "audio-track.m4a"
        for target, options in ((cls.video, ["-an"]), (cls.audio, ["-vn"])):
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(cls.source)] + options
                           + ["-c", "copy", str(target)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_full_frames_pts_precise_frame_and_audio(self):
        out = self.root / "analysis"
        manifest = prepare(self.source, out, interval=0.5, at=[0.26], audio=True)
        data = json.loads(manifest.read_text())
        self.assertEqual(len(data["frames"]), 5)
        self.assertEqual([item["timestamp_seconds"] for item in data["frames"]],
                         [0, 0.5, 1, 1.5, 2])
        self.assertAlmostEqual(data["detail_frames"][0]["timestamp_seconds"], 0.3)
        self.assertFalse(data["recognition_performed"])
        audio = probe(out / "audio.wav")
        self.assertEqual(audio["streams"][0]["sample_rate"], "16000")
        self.assertEqual(audio["streams"][0]["channels"], 1)
        self.assertTrue((out / data["sheets"][0]["file"]).is_file())
        self.assertEqual(probe(out / data["frames"][0]["file"])["streams"][0]["width"], 160)
        with self.assertRaises(ValueError):
            prepare(self.source, out)

    def test_invalid_timestamp_and_interval_do_not_create_output(self):
        out = self.root / "invalid"
        for kwargs in ({"at": [-1]}, {"at": [99]}, {"interval": float("nan")},
                       {"interval": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                prepare(self.source, out, **kwargs)
            self.assertFalse(out.exists())

    def test_missing_tracks_are_explicit(self):
        with self.assertRaisesRegex(ValueError, "没有视频轨"):
            prepare(self.audio, self.root / "audio-only")
        with self.assertRaisesRegex(ValueError, "没有音频轨"):
            prepare(self.video, self.root / "missing-audio", audio=True)

    def test_split_track_merge_without_live_network(self):
        config = {"page_url": "https://www.douyin.com/video/123456",
                  "user_agent": "Test Browser",
                  "video_url": "https://v.douyinvod.com/video?signature=TEST_ONLY",
                  "audio_url": "https://v.douyinvod.com/audio?signature=TEST_ONLY"}

        def local_download(url, target, *args):
            shutil.copyfile(self.audio if "/audio?" in url else self.video, target)

        with patch("download_douyin_media.curl_download", side_effect=local_download):
            result = download(config, self.root / "merged")
        info = probe(result)
        self.assertTrue(has_stream(info, "video"))
        self.assertTrue(has_stream(info, "audio"))
        metadata = (result.parent / "source.json").read_text()
        self.assertNotIn("signature=", metadata)
        self.assertEqual(json.loads(metadata)["content_id"], "123456")


if __name__ == "__main__":
    unittest.main()
