"""Pruebas del corte de descargas y de la lista concat de bajo uso de RAM."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import DownloadConfig, SmnConfig  # noqa: E402
from downloader import ImageDownloader  # noqa: E402
from frame_plan import FramePlan  # noqa: E402
from renderer import _group_consecutive_frames, _write_concat_list  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


class _FakeClient:
    def __init__(self, status_code: int = 403) -> None:
        self.status_code = status_code
        self.calls = 0
        self.cookies = {}

        class _Cookies:
            def set(self, *args, **kwargs):  # noqa: ANN002, ANN003
                return None

        self.cookies = _Cookies()

    def get(self, url, headers=None):  # noqa: ANN001
        self.calls += 1
        return _FakeResponse(self.status_code, b"<html>just a moment</html>")


def _download_config(**overrides):
    values = dict(
        buffer_dir=Path("buffer"),
        request_timeout_seconds=5.0,
        max_retries=3,
        delay_between_downloads_seconds=0.0,
        use_browser_fallback=True,
        developer_mode=False,
        max_consecutive_failures=3,
    )
    values.update(overrides)
    return DownloadConfig(**values)


def _smn():
    return SmnConfig(
        api_base_url="https://example.test",
        static_base_url="https://static.example.test",
        username="u",
        password="p",
        token_server_url="",
    )


class CircuitBreakerTests(unittest.TestCase):
    def test_skips_rest_after_consecutive_cloudflare_failures(self) -> None:
        client = _FakeClient(status_code=403)
        downloader = ImageDownloader(_smn(), _download_config(use_browser_fallback=False), client)
        downloader.begin_cycle()

        self.assertIsNone(downloader.download("a.jpg"))
        self.assertIsNone(downloader.download("b.jpg"))
        self.assertIsNone(downloader.download("c.jpg"))
        self.assertTrue(downloader.skipping_remaining)

        before = client.calls
        self.assertIsNone(downloader.download("d.jpg"))
        self.assertEqual(client.calls, before)

    def test_cloudflare_does_not_retry_http_three_times(self) -> None:
        client = _FakeClient(status_code=403)
        downloader = ImageDownloader(_smn(), _download_config(use_browser_fallback=False), client)
        downloader.begin_cycle()
        downloader.download("a.jpg")
        self.assertEqual(client.calls, 1)

    def test_begin_cycle_clears_the_breaker(self) -> None:
        client = _FakeClient(status_code=403)
        downloader = ImageDownloader(_smn(), _download_config(use_browser_fallback=False), client)
        downloader.begin_cycle()
        for name in ("a.jpg", "b.jpg", "c.jpg"):
            downloader.download(name)
        self.assertTrue(downloader.skipping_remaining)
        downloader.begin_cycle()
        self.assertFalse(downloader.skipping_remaining)

    def test_browser_is_not_relaunched_after_one_failure(self) -> None:
        client = _FakeClient(status_code=403)
        downloader = ImageDownloader(_smn(), _download_config(), client)
        downloader.begin_cycle()

        with patch.object(downloader, "_fetch_with_browser", return_value=None) as browser:
            self.assertIsNone(downloader.download("a.jpg"))
            self.assertIsNone(downloader.download("b.jpg"))
            browser.assert_called_once()


class ConcatListTests(unittest.TestCase):
    def test_groups_repeated_frames_with_duration(self) -> None:
        a = Path("arg.jpg")
        b = Path("cen.jpg")
        frames = [a, a, a, b, b]
        groups = _group_consecutive_frames(frames)
        self.assertEqual(groups, [(a, 3), (b, 2)])

        unique = {a: Path("frames") / "u000.jpg", b: Path("frames") / "u001.jpg"}
        concat = Path("/tmp/frames.txt")
        plan = FramePlan(frames=frames, slots=[a, b], fps=30)
        _write_concat_list(plan, unique, concat)
        text = concat.read_text(encoding="utf-8")
        self.assertIn("file 'u000.jpg'", text)
        self.assertIn("duration 0.100000", text)
        self.assertIn("file 'u001.jpg'", text)
        self.assertIn("duration 0.066667", text)
        self.assertTrue(text.strip().endswith("file 'u001.jpg'"))


if __name__ == "__main__":
    unittest.main()
