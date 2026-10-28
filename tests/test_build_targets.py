"""
B10: each PyInstaller target ships only the native binaries (TeamTalk SDK,
libmpv, ffmpeg) it can actually load at runtime, instead of all three on
every target regardless of need.

build/build.py and build/package_rental.py are not (and should not become)
importable packages, so they are loaded here as plain modules -- the exact
pattern core/manager.py and core/command_manager.py already use for
plugins. No PyInstaller run, no subprocess: build_command() only builds the
argument list.
"""

import importlib.util
import os
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_module(relative_path, name):
    path = os.path.join(PROJECT_ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_module(os.path.join("build", "build.py"), "_test_build_module")

# فقط bot واقعاً صدا پخش/ضبط می‌کنه: bot.py مستقیم و توی سطح ماژول
# teamtalk.ttbot، teamtalk.TeamTalk5 و mpv.player رو import می‌کنه، و از
# platform_paths.ffmpeg_location()/has_ffmpeg() برای yt-dlp استفاده می‌کنه.
# launcher/license بقیه‌ی ربات‌ها رو با subprocess.Popen بالا می‌آرن (نه
# import مستقیم)؛ manage دستگاه‌ها رو تابعی و توی try/except چک می‌کنه
# (core/audio_lines.py) و نبودشون رو با پیام روشن گزارش می‌ده، نه کرش.
# جزئیات و شواهد کامل: docs/BUILD.md.
EXPECTED_NATIVE = {
    "bot": {"teamtalk", "mpv", "ffmpeg", "xray"},
    "launcher": set(),
    "license": set(),
    "manage": set(),
}


class TargetNativeListsTest(unittest.TestCase):

    def test_declared_targets_match_expected_set(self):
        self.assertEqual(set(build.TARGETS), set(EXPECTED_NATIVE))

    def test_native_lists_match_the_evidence(self):
        for key, expected in EXPECTED_NATIVE.items():
            with self.subTest(target=key):
                self.assertEqual(set(build.TARGETS[key].get("native", [])), expected)

    def test_every_declared_native_key_is_known(self):
        # یه کلید native تایپو شده هیچ خطایی نمی‌ده -- فقط بی‌صدا هیچ
        # فایلی اضافه نمی‌کنه. این تست جلوی اون سکوت رو می‌گیره.
        for key, target in build.TARGETS.items():
            for native_key in target.get("native", []):
                with self.subTest(target=key, native=native_key):
                    self.assertIn(native_key, build.NATIVE_FILES)


class BuildCommandTest(unittest.TestCase):
    """
    build_command() فقط لیست آرگومان‌های PyInstaller رو می‌سازه (بدون
    subprocess)، پس این تست‌ها بدون بیلد واقعی و بدون نیاز به نصب بودن
    PyInstaller اجرا می‌شن.
    """

    def setUp(self):
        # فایل‌ها رو *موجود* فرض می‌کنیم تا تست به این بستگی نداشته باشه که
        # bin/ffmpeg.exe (که .gitignore شده و روی هر ماشینی نیست) توی این
        # worktree واقعاً هست یا نه.
        patcher = mock.patch("os.path.isfile", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_non_audio_targets_get_no_add_binary(self):
        for key in ("launcher", "license", "manage"):
            with self.subTest(target=key):
                command = build.build_command(key, onefile=False, use_upx=False)
                self.assertNotIn("--add-binary", command)

    def test_bot_gets_an_add_binary_per_native_candidate(self):
        command = build.build_command("bot", onefile=False, use_upx=False)
        add_binary_count = command.count("--add-binary")
        # هر کدوم از سه native یه لیست کاندید (ویندوز/لینوکس) داره؛ با
        # os.path.isfile همیشه True، هر کاندیدی --add-binary خودش رو می‌گیره.
        expected = sum(len(candidates) for candidates in build.NATIVE_FILES.values())
        self.assertEqual(add_binary_count, expected)

    def test_bot_add_binary_sources_name_every_native_file(self):
        command = build.build_command("bot", onefile=False, use_upx=False)
        sources = " ".join(command)
        for candidates in build.NATIVE_FILES.values():
            for relative in candidates:
                with self.subTest(file=relative):
                    self.assertIn(os.path.basename(relative), sources)

    def test_data_dirs_still_bundled_for_every_target(self):
        # این تغییر فقط native ها رو per-target کرد؛ commands/languages/
        # core.services باید برای هر چهار هدف دست‌نخورده بمونه.
        for key in build.TARGETS:
            with self.subTest(target=key):
                command = build.build_command(key, onefile=False, use_upx=False)
                self.assertIn("--add-data", command)

    def test_script_is_the_last_argument(self):
        for key, target in build.TARGETS.items():
            with self.subTest(target=key):
                command = build.build_command(key, onefile=False, use_upx=False)
                self.assertTrue(command[-1].endswith(target["script"]))


class PackageRentalNativeCheckTest(unittest.TestCase):
    """
    build/package_rental.py باید همون لیست native هدف bot (تنها هدفی که
    واقعاً توی بسته‌ی مشتری می‌ره) رو برای تحویل مشتری چک کنه، از همون
    منبعی که build.py استفاده می‌کنه -- نه یه کپی‌ی جدا.
    """

    @classmethod
    def setUpClass(cls):
        cls.package_rental = _load_module(
            os.path.join("build", "package_rental.py"), "_test_package_rental_module")

    def test_empty_package_is_missing_every_bot_native(self):
        with tempfile.TemporaryDirectory(prefix="b10_test_") as tmp:
            missing = self.package_rental._missing_native_components(tmp)
        self.assertEqual(set(missing), EXPECTED_NATIVE["bot"])

    def test_package_with_internal_natives_is_complete(self):
        with tempfile.TemporaryDirectory(prefix="b10_test_") as tmp:
            # مثل onedir واقعی: --add-binary ها زیر _internal/ در می‌آن.
            internal = os.path.join(tmp, "_internal")
            for key in build.TARGETS["bot"]["native"]:
                for relative in build.NATIVE_FILES[key]:
                    path = os.path.join(internal, relative)
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    open(path, "w").close()
            missing = self.package_rental._missing_native_components(tmp)
        self.assertEqual(missing, [])

    def test_inspect_fails_when_natives_are_missing(self):
        with tempfile.TemporaryDirectory(prefix="b10_test_") as tmp:
            self.assertEqual(self.package_rental.inspect(tmp), 1)


if __name__ == "__main__":
    unittest.main()
