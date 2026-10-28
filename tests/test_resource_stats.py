"""آمار منابع، دستور res، و lazy بودن yt-dlp موقع import ربات."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from core import resource_stats, ytdlp_lazy
from tests.helpers import ROOT, load_command


class Snapshot(unittest.TestCase):
    def test_fields(self):
        s = resource_stats.snapshot()
        self.assertGreater(s["rss_mb"], 1)
        self.assertGreaterEqual(s["threads"], 1)
        self.assertGreaterEqual(s["cpu_seconds"], 0)

    def test_fallback_without_psutil(self):
        with mock.patch.object(resource_stats, "psutil", None):
            s = resource_stats.snapshot(start_time=1.0)
        self.assertGreaterEqual(s["threads"], 1)
        self.assertIsNotNone(s["uptime"])


class ResCommand(unittest.TestCase):
    def test_admin_only_and_sends_message(self):
        cmd = load_command("res")
        self.assertEqual(cmd.REQUIRED_ROLE, "admin_bot")
        bot = mock.Mock(start_time=0)
        bot.format_time.return_value = "1 second"
        cmd.run({"bot": bot, "uid": 7})
        self.assertEqual(bot.t.user_message.call_args[0][0], 7)

    def test_i18n_placeholders_match(self):
        import re
        langs = {}
        for l in ("en", "fa"):
            with open(os.path.join(ROOT, "languages", l + ".json"), encoding="utf-8") as f:
                langs[l] = json.load(f)
        for key in ("res_info", "res_na"):
            found = []
            for l, d in langs.items():
                node = d
                while isinstance(node, dict) and key not in node:
                    node = next((v for v in node.values() if isinstance(v, dict) and key in v), None)
                self.assertIsNotNone(node, (l, key))
                found.append(set(re.findall(r"\{(\w+)\}", node[key])))
            self.assertEqual(found[0], found[1])


class LazyYtdlp(unittest.TestCase):
    def test_import_bot_does_not_load_ytdlp(self):
        code = "import sys;sys.argv=['bot.py']\ntry:\n import bot\nexcept BaseException:\n pass\nprint('yt_dlp' in sys.modules)"
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=dict(os.environ, PYTHONPATH=ROOT),
                             capture_output=True, text=True).stdout.split()[-1]
        self.assertEqual(out, "False")

    def test_shims_resolve_real_classes(self):
        import yt_dlp
        self.assertIs(ytdlp_lazy.download_error(), yt_dlp.utils.DownloadError)
        with ytdlp_lazy.YoutubeDL({"quiet": True}) as ydl:
            self.assertIsInstance(ydl, yt_dlp.YoutubeDL)


if __name__ == "__main__":
    unittest.main()
