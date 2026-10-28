"""
E16: native components (TeamTalk SDK، libmpv، ffmpeg) توی بیلدِ کامپایل‌شده
پیدا نمی‌شدن، چون core.platform_paths مسیرها رو با core.paths.get_base_dir()
می‌ساخت -- پوشه‌ی خودِ فایل اجرایی -- درحالی‌که PyInstaller 6 در حالت
onedir فایل‌های --add-binary رو زیر _internal/ می‌ذاره (از طریق
sys._MEIPASS)، نه کنار .exe. در onefile هم فایل‌ها توی پوشه‌ی موقتِ
sys._MEIPASS باز می‌شن که اصلاً زیرشاخه‌ی پوشه‌ی exe نیست.

این تست‌ها core.platform_paths.find_native_component() (و توابعی که
رویش سوارن) رو برای هر چهار حالت استقرار ممکن شبیه‌سازی می‌کنن -- با
پوشه‌ی موقت روی دیسک و patch کردن sys.frozen/sys._MEIPASS/sys.executable/
sys.platform -- بدون هیچ DLL/so واقعی:

    ۱. اجرای مستقیم از سورس (بدون mock -- خودِ محیط واقعیِ این ریپو).
    ۲. بیلدِ onedir: فایل‌ها زیر <پوشه‌ی exe>/_internal/.
    ۳. بیلدِ onefile: فایل‌ها زیر پوشه‌ی موقتِ sys._MEIPASS (کاملاً جدا از
       پوشه‌ی exe).
    ۴. کپیِ دستیِ کاربر کنار فایل اجرایی -- که باید همیشه برنده بشه، چه
       روی onedir چه روی onefile.
"""

import ctypes
import os
import sys
import tempfile
import unittest
from unittest import mock

from core import platform_paths


def _touch(path, content=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


class NativeLayoutTestCase(unittest.TestCase):
    """
    پایه‌ی مشترک برای شبیه‌سازیِ یه حالت استقرار: یه پوشه‌ی موقت روی دیسک
    + patch واقعیِ sys.frozen/sys._MEIPASS/sys.executable (همونی که
    core.paths.get_base_dir()/bundle_dir() واقعاً می‌خونن) تا خودِ
    core.paths هم توی مسیر تست باشه، نه فقط core.platform_paths.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(prefix="platform_paths_test_")
        self.addCleanup(self._tmpdir.cleanup)
        self.root = self._tmpdir.name

    def _patch_sys(self, **attrs):
        for name, value in attrs.items():
            patcher = mock.patch.object(sys, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def onedir_layout(self, exe_subdir=os.path.join("dist", "ttbot"), exe_name="ttbot.exe"):
        """
        بیلدِ onedir با PyInstaller 6+: --add-binary ها زیر _internal/ در
        می‌آن؛ sys._MEIPASS هم به همون _internal/ اشاره می‌کنه.
        """
        exe_root = os.path.join(self.root, exe_subdir)
        internal = os.path.join(exe_root, "_internal")
        os.makedirs(internal, exist_ok=True)
        self._patch_sys(frozen=True, executable=os.path.join(exe_root, exe_name), _MEIPASS=internal)
        return exe_root, internal

    def onefile_layout(self, exe_subdir="dist", exe_name="ttbot.exe"):
        """
        بیلدِ onefile: exe تنها و بدون هیچ زیرپوشه‌ای؛ فایل‌ها توی یه
        پوشه‌ی موقتِ کاملاً جدا (شبیه‌سازیِ %TEMP%\\_MEIxxxxx) باز می‌شن.
        """
        exe_root = os.path.join(self.root, exe_subdir)
        extract_dir = os.path.join(self.root, "_MEI123456")
        os.makedirs(exe_root, exist_ok=True)
        os.makedirs(extract_dir, exist_ok=True)
        self._patch_sys(frozen=True, executable=os.path.join(exe_root, exe_name), _MEIPASS=extract_dir)
        return exe_root, extract_dir


class FindNativeComponentTest(NativeLayoutTestCase):

    def test_source_run_finds_the_real_project_files(self):
        # بدون هیچ patch ای: دقیقاً همون چیزی که این ریپو روی دیسک داره.
        # (خودِ کارگاه ویندوزیه؛ teamtalk/TeamTalk5.dll و mpv/libmpv-2.dll
        # همراه پروژه‌ان -- ببین core/platform_paths.py.)
        found = platform_paths.find_native_component("teamtalk")
        self.assertIsNotNone(found)
        self.assertTrue(os.path.isfile(found))
        self.assertEqual(os.path.basename(found), "TeamTalk5.dll")

    def test_onedir_build_finds_file_under_internal(self):
        exe_root, internal = self.onedir_layout()
        _touch(os.path.join(internal, "core", "teamtalk", "TeamTalk5.dll"))

        found = platform_paths.find_native_component("teamtalk")

        self.assertEqual(found, os.path.join(internal, "core", "teamtalk", "TeamTalk5.dll"))

    def test_onedir_build_missing_file_returns_none(self):
        self.onedir_layout()
        self.assertIsNone(platform_paths.find_native_component("teamtalk"))

    def test_onefile_build_finds_file_under_meipass(self):
        exe_root, extract_dir = self.onefile_layout()
        _touch(os.path.join(extract_dir, "core", "mpv", "libmpv-2.dll"))

        found = platform_paths.find_native_component("mpv")

        self.assertEqual(found, os.path.join(extract_dir, "core", "mpv", "libmpv-2.dll"))
        # نکته‌ی اصلیِ onefile: پوشه‌ی استخراج زیرشاخه‌ی پوشه‌ی exe نیست.
        self.assertFalse(found.startswith(exe_root))

    def test_user_override_next_to_exe_wins_over_onedir_bundle(self):
        exe_root, internal = self.onedir_layout()
        _touch(os.path.join(internal, "core", "teamtalk", "TeamTalk5.dll"), content="bundled")
        override = _touch(os.path.join(exe_root, "core", "teamtalk", "TeamTalk5.dll"), content="customer override")

        found = platform_paths.find_native_component("teamtalk")

        self.assertEqual(found, override)
        with open(found) as f:
            self.assertEqual(f.read(), "customer override")

    def test_user_override_next_to_exe_wins_over_onefile_bundle(self):
        exe_root, extract_dir = self.onefile_layout()
        _touch(os.path.join(extract_dir, "core", "mpv", "libmpv-2.dll"), content="bundled")
        override = _touch(os.path.join(exe_root, "core", "mpv", "libmpv-2.dll"), content="customer override")

        found = platform_paths.find_native_component("mpv")

        self.assertEqual(found, override)

    def test_onedir_without_override_still_falls_back_to_bundle(self):
        # override نبودن نباید جلوی پیدا شدنِ نسخه‌ی باندل‌شده رو بگیره.
        exe_root, internal = self.onedir_layout()
        bundled = _touch(os.path.join(internal, "bin", "ffmpeg.exe"))

        found = platform_paths.find_native_component("ffmpeg")

        self.assertEqual(found, bundled)


class OsSpecificNamingTest(NativeLayoutTestCase):
    """
    اسمِ فایل باید از روی sys.platform *لحظه‌ی صدازدن* انتخاب بشه، نه یه
    ثابتِ سطح ماژول -- وگرنه این تست‌ها بدون ری‌استارتِ پروسه امکان‌پذیر
    نبودن.
    """

    def test_windows_looks_for_dll_not_so(self):
        exe_root, internal = self.onedir_layout()
        _touch(os.path.join(internal, "core", "teamtalk", "libTeamTalk5.so"))  # لینوکسی، نباید پیدا بشه
        with mock.patch.object(sys, "platform", "win32"):
            self.assertIsNone(platform_paths.find_native_component("teamtalk"))
            self.assertEqual(platform_paths.teamtalk_library_names(), ("TeamTalk5.dll",))

    def test_linux_looks_for_so_not_dll(self):
        exe_root, internal = self.onedir_layout()
        found_path = _touch(os.path.join(internal, "core", "teamtalk", "libTeamTalk5.so"))
        with mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(platform_paths.find_native_component("teamtalk"), found_path)
            self.assertEqual(platform_paths.teamtalk_library_names(), ("libTeamTalk5.so",))

    def test_macos_names_are_distinct(self):
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(platform_paths.teamtalk_library_names(), ("libTeamTalk5.dylib",))
            self.assertIn("libmpv.dylib", platform_paths.mpv_library_names())

    def test_mpv_accepts_any_of_its_windows_alternate_names(self):
        exe_root, internal = self.onedir_layout()
        found_path = _touch(os.path.join(internal, "core", "mpv", "mpv-1.dll"))
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(platform_paths.find_native_component("mpv"), found_path)

    def test_native_component_all_names_covers_every_platform_without_duplicates(self):
        names = platform_paths.native_component_all_names("teamtalk")
        self.assertEqual(set(names), {"TeamTalk5.dll", "libTeamTalk5.so", "libTeamTalk5.dylib"})
        self.assertEqual(len(names), len(set(names)))


class FfmpegLookupTest(NativeLayoutTestCase):

    def test_ffmpeg_location_is_none_when_only_found_on_path(self):
        self.onedir_layout()
        with mock.patch("core.platform_paths.find_native_component", return_value=None), \
             mock.patch("shutil.which", return_value=r"C:\Windows\ffmpeg.exe"):
            self.assertTrue(platform_paths.has_ffmpeg())
            self.assertIsNone(platform_paths.ffmpeg_location())

    def test_ffmpeg_location_is_bundle_dir_when_bundled_in_onedir(self):
        exe_root, internal = self.onedir_layout()
        _touch(os.path.join(internal, "bin", "ffmpeg.exe"))

        self.assertEqual(platform_paths.ffmpeg_location(), os.path.join(internal, "bin"))
        self.assertTrue(platform_paths.has_ffmpeg())

    def test_ffmpeg_location_is_none_when_nothing_found(self):
        self.onedir_layout()
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(platform_paths.has_ffmpeg())
            self.assertIsNone(platform_paths.ffmpeg_location())
            self.assertIsNone(platform_paths.ffmpeg_binary())


class DelegationTest(NativeLayoutTestCase):
    """
    teamtalk_library_path/mpv_library_path باید صرفاً find_native_component
    رو صدا بزنن -- یه تصمیم، یه جا.
    """

    def test_teamtalk_and_mpv_paths_delegate_to_find_native_component(self):
        with mock.patch("core.platform_paths.find_native_component", side_effect=lambda c: f"/resolved/{c}") as m:
            self.assertEqual(platform_paths.teamtalk_library_path(), "/resolved/teamtalk")
            self.assertEqual(platform_paths.mpv_library_path(), "/resolved/mpv")
            m.assert_any_call("teamtalk")
            m.assert_any_call("mpv")


class MissingRuntimeRequirementsTest(NativeLayoutTestCase):
    """
    مسدود کردنِ ctypes.util.find_library/ctypes.CDLL لازمه چون اگه یه تست
    دیگه قبلاً teamtalk/mpv واقعیِ این ریپو رو import کرده باشه،
    prepare_native_libraries() پوشه‌های واقعی رو به PATH اضافه کرده و
    lookup بی‌مسیرِ ctypes.CDLL می‌تونه قاطی بشه.
    """

    def test_everything_missing_reports_all_three(self):
        self.onedir_layout()
        with mock.patch("ctypes.util.find_library", return_value=None), \
             mock.patch("ctypes.CDLL", side_effect=OSError("not found")), \
             mock.patch("shutil.which", return_value=None):
            problems = platform_paths.missing_runtime_requirements()
        joined = " | ".join(problems)
        self.assertIn("TeamTalk SDK", joined)
        self.assertIn("libmpv", joined)
        self.assertIn("ffmpeg", joined)

    def test_everything_present_reports_nothing(self):
        exe_root, internal = self.onedir_layout()
        _touch(os.path.join(internal, "core", "teamtalk", "TeamTalk5.dll"))
        _touch(os.path.join(internal, "core", "mpv", "libmpv-2.dll"))
        _touch(os.path.join(internal, "bin", "ffmpeg.exe"))

        self.assertEqual(platform_paths.missing_runtime_requirements(), [])
        summary = platform_paths.describe_runtime()
        self.assertIn("teamtalk=bundled", summary)
        self.assertIn("mpv=bundled", summary)
        self.assertIn("ffmpeg=yes", summary)

    def test_describe_runtime_reports_system_when_not_bundled_but_on_path(self):
        self.onedir_layout()
        with mock.patch("core.platform_paths.find_native_component", return_value=None), \
             mock.patch("shutil.which", return_value=r"C:\Windows\ffmpeg.exe"):
            summary = platform_paths.describe_runtime()
        self.assertIn("teamtalk=system", summary)
        self.assertIn("mpv=system", summary)
        self.assertIn("ffmpeg=yes", summary)


class PrepareNativeLibrariesTest(NativeLayoutTestCase):

    def test_adds_both_exe_adjacent_and_bundle_dirs_on_onedir(self):
        exe_root, internal = self.onedir_layout()
        os.makedirs(os.path.join(exe_root, "core", "teamtalk"), exist_ok=True)
        os.makedirs(os.path.join(internal, "core", "teamtalk"), exist_ok=True)

        with mock.patch.object(platform_paths, "_prepared", False), \
             mock.patch.object(platform_paths, "IS_WINDOWS", True), \
             mock.patch("os.add_dll_directory", create=True) as added:
            platform_paths.prepare_native_libraries()

        added_dirs = {call.args[0] for call in added.call_args_list}
        self.assertIn(os.path.join(exe_root, "core", "teamtalk"), added_dirs)
        self.assertIn(os.path.join(internal, "core", "teamtalk"), added_dirs)

    def test_is_idempotent_within_a_process(self):
        self.onedir_layout()
        with mock.patch.object(platform_paths, "_prepared", False), \
             mock.patch.object(platform_paths, "IS_WINDOWS", True), \
             mock.patch("os.add_dll_directory", create=True) as added:
            platform_paths.prepare_native_libraries()
            first_call_count = added.call_count
            platform_paths.prepare_native_libraries()
            self.assertEqual(added.call_count, first_call_count)


class JsRuntimeTest(NativeLayoutTestCase):
    """E9: platform_paths.js_runtime() -- فقط *پیدا کردن*، وصل کردن به yt-dlp جای دیگه‌ست."""

    def test_bundled_deno_wins_over_everything(self):
        with mock.patch("core.platform_paths.find_native_component",
                         side_effect=lambda c: r"C:\ttbot\bin\deno.exe" if c == "deno" else None), \
             mock.patch("shutil.which", return_value=r"C:\Windows\node.exe"):
            self.assertEqual(platform_paths.js_runtime(), {"deno": {"path": r"C:\ttbot\bin\deno.exe"}})

    def test_path_deno_wins_over_path_node(self):
        def which(name):
            return {"deno": "/usr/bin/deno", "node": "/usr/bin/node"}.get(name)

        with mock.patch("core.platform_paths.find_native_component", return_value=None), \
             mock.patch("shutil.which", side_effect=which):
            self.assertEqual(platform_paths.js_runtime(), {"deno": {"path": "/usr/bin/deno"}})

    def test_falls_back_to_node_when_no_deno_anywhere(self):
        def which(name):
            return {"node": "/usr/bin/node"}.get(name)

        with mock.patch("core.platform_paths.find_native_component", return_value=None), \
             mock.patch("shutil.which", side_effect=which):
            self.assertEqual(platform_paths.js_runtime(), {"node": {"path": "/usr/bin/node"}})

    def test_empty_dict_when_neither_is_available(self):
        with mock.patch("core.platform_paths.find_native_component", return_value=None), \
             mock.patch("shutil.which", return_value=None):
            self.assertEqual(platform_paths.js_runtime(), {})


if __name__ == "__main__":
    unittest.main()
