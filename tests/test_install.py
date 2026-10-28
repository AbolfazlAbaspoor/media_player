"""
E9: install.py -- نصب یک‌مرحله‌ای وابستگی‌های پایتون و کامپوننت‌های نیتیو.

هیچ‌کدوم از این تست‌ها واقعاً دانلود/نصب نمی‌کنن: install._download و
install._http_get_json (تنها دو نقطه‌ای که این اسکریپت به شبکه وصل می‌شه)
همه‌جا mock می‌شن، و توی تست‌های dry-run طوری patch می‌شن که اگه صدا زده
بشن AssertionError بدن -- دقیقاً همون چیزی که مشخصات E9 می‌خواد:
«--dry-run هیچ فراخوانیِ شبکه‌ای نداره».
"""

import io
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import install
from core import platform_paths


def _network_should_not_be_called(*_a, **_k):
    raise AssertionError("--dry-run نباید هیچ تابع شبکه‌ای‌ای رو صدا بزنه")


def _silent(fn, *args, **kwargs):
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


class ComponentTableTest(unittest.TestCase):
    """جدولِ کامپوننت‌ها: xray اختیاریه (طبق مشخصات E9)، بقیه پیش‌فرضن."""

    def test_xray_is_optional_not_default(self):
        self.assertNotIn("xray", install.DEFAULT_COMPONENTS)
        self.assertIn("xray", install.ALL_COMPONENTS)

    def test_every_default_component_has_a_label(self):
        for name in install.ALL_COMPONENTS:
            with self.subTest(component=name):
                self.assertIn(name, install.COMPONENT_LABELS)

    def test_destinations_come_from_platform_paths_not_a_new_list(self):
        # E9 نباید یه لیست مسیرِ جدا برای مقصدها بسازه -- همون رجیستریِ
        # E16 (core.platform_paths.NATIVE_COMPONENTS) باید منبع باشه.
        for component in ("teamtalk", "ffmpeg", "mpv", "deno", "xray"):
            with self.subTest(component=component):
                self.assertIn(component, platform_paths.NATIVE_COMPONENTS)


class DryRunMakesNoNetworkCallsTest(unittest.TestCase):
    """
    همه‌ی کامپوننت‌ها رو «هنوز نصب نشده» فرض می‌کنیم (بدترین حالت -- همه
    باید بخوان دانلود کنن) و بعد چک می‌کنیم --dry-run واقعاً هیچی دانلود
    نمی‌کنه.
    """

    def setUp(self):
        patchers = [
            mock.patch("install._download", side_effect=_network_should_not_be_called),
            mock.patch("install._http_get_json", side_effect=_network_should_not_be_called),
            mock.patch.object(platform_paths, "find_native_component", return_value=None),
            mock.patch.object(platform_paths, "has_ffmpeg", return_value=False),
            mock.patch.object(platform_paths, "js_runtime", return_value={}),
            mock.patch("install._mpv_present", return_value=False),
            mock.patch("shutil.which", return_value=None),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_dry_run_all_components_on_windows(self):
        with mock.patch.object(platform_paths, "IS_WINDOWS", True), \
             mock.patch.object(platform_paths, "IS_LINUX", False):
            code, output = _silent(install.main, ["--dry-run", "--components", ",".join(install.ALL_COMPONENTS)])
        self.assertEqual(code, 0)
        self.assertIn("dry-run", output)

    def test_dry_run_all_components_on_linux_without_package_manager(self):
        with mock.patch.object(platform_paths, "IS_WINDOWS", False), \
             mock.patch.object(platform_paths, "IS_LINUX", True):
            code, output = _silent(install.main, ["--dry-run", "--components", ",".join(install.ALL_COMPONENTS)])
        self.assertEqual(code, 0)

    def test_dry_run_with_venv_and_licensing_touches_no_network(self):
        code, _ = _silent(install.main, ["--dry-run", "--with-licensing", "--venv", ".venv-should-not-exist"])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.isdir(os.path.join(install.PROJECT_DIR, ".venv-should-not-exist")))


class IdempotencyTest(unittest.TestCase):
    """وقتی همه‌چیز از قبل کار می‌کنه، هیچ نصب/دانلودی نباید انجام بشه."""

    def test_everything_present_skips_every_step(self):
        with mock.patch.object(platform_paths, "find_native_component", return_value=r"C:\ttbot\teamtalk\TeamTalk5.dll"), \
             mock.patch.object(platform_paths, "has_ffmpeg", return_value=True), \
             mock.patch.object(platform_paths, "ffmpeg_binary", return_value=r"C:\ttbot\bin\ffmpeg.exe"), \
             mock.patch.object(platform_paths, "js_runtime", return_value={"deno": {"path": "/usr/bin/deno"}}), \
             mock.patch("install._mpv_present", return_value=True), \
             mock.patch("install._download", side_effect=_network_should_not_be_called), \
             mock.patch("install._http_get_json", side_effect=_network_should_not_be_called), \
             mock.patch("subprocess.run", side_effect=AssertionError("نباید هیچ دستوری اجرا بشه")):
            results, _ = _silent(install.run, ["teamtalk", "ffmpeg", "libmpv", "js_runtime"],
                                  dry_run=False, with_licensing=False, venv=None)
        self.assertTrue(all(status == install.Status.OK for status in results.values()), results)

    def test_second_run_is_still_a_noop(self):
        # idempotent یعنی چند بار پشتِ‌سرهم زدن هم فرقی نداره.
        with mock.patch.object(platform_paths, "find_native_component", return_value="/present"), \
             mock.patch("install._download", side_effect=_network_should_not_be_called):
            first, _ = _silent(install.run, ["teamtalk"], dry_run=False, with_licensing=False, venv=None)
            second, _ = _silent(install.run, ["teamtalk"], dry_run=False, with_licensing=False, venv=None)
        self.assertEqual(first, second)
        self.assertEqual(first["teamtalk"], install.Status.OK)


class ComponentSelectionTest(unittest.TestCase):

    def test_only_selected_components_run(self):
        with mock.patch("install.do_ffmpeg", return_value=install.Status.OK) as ffmpeg_mock, \
             mock.patch("install.do_teamtalk", return_value=install.Status.OK) as teamtalk_mock, \
             mock.patch("install.do_libmpv", return_value=install.Status.OK) as libmpv_mock:
            code, _ = _silent(install.main, ["--dry-run", "--components", "ffmpeg"])
        self.assertEqual(code, 0)
        ffmpeg_mock.assert_called_once()
        teamtalk_mock.assert_not_called()
        libmpv_mock.assert_not_called()

    def test_unknown_component_is_rejected_with_exit_code_2(self):
        code, output = _silent(install.main, ["--dry-run", "--components", "not-a-real-component"])
        self.assertEqual(code, 2)
        self.assertIn("ناشناس", output)

    def test_xray_only_runs_when_explicitly_requested(self):
        with mock.patch("install.do_xray", return_value=install.Status.OK) as xray_mock:
            _silent(install.main, ["--dry-run"])  # پیش‌فرض، بدون xray
            xray_mock.assert_not_called()
            _silent(install.main, ["--dry-run", "--components", "xray"])
            xray_mock.assert_called_once()


class PlanPerPlatformTest(unittest.TestCase):
    """پلن باید منبع درستِ همون سیستم‌عامل رو نشون بده."""

    def test_windows_ffmpeg_plan_mentions_btbn_win64(self):
        with mock.patch.object(platform_paths, "has_ffmpeg", return_value=False), \
             mock.patch.object(platform_paths, "IS_WINDOWS", True), \
             mock.patch.object(platform_paths, "IS_LINUX", False):
            _, output = _silent(install.do_ffmpeg, True)
        self.assertIn("win64", output)
        self.assertIn("BtbN", output)

    def test_linux_ffmpeg_plan_prefers_package_manager(self):
        with mock.patch.object(platform_paths, "has_ffmpeg", return_value=False), \
             mock.patch.object(platform_paths, "IS_WINDOWS", False), \
             mock.patch.object(platform_paths, "IS_LINUX", True), \
             mock.patch("install._package_manager", return_value="apt"):
            _, output = _silent(install.do_ffmpeg, True)
        self.assertIn("apt", output)

    def test_linux_without_package_manager_falls_back_to_direct_download_plan(self):
        with mock.patch.object(platform_paths, "has_ffmpeg", return_value=False), \
             mock.patch.object(platform_paths, "IS_WINDOWS", False), \
             mock.patch.object(platform_paths, "IS_LINUX", True), \
             mock.patch("install._package_manager", return_value=None):
            _, output = _silent(install.do_ffmpeg, True)
        self.assertIn("linux64", output)

    def test_windows_libmpv_plan_mentions_shinchiro(self):
        with mock.patch("install._mpv_present", return_value=False), \
             mock.patch.object(platform_paths, "IS_WINDOWS", True), \
             mock.patch.object(platform_paths, "IS_LINUX", False):
            _, output = _silent(install.do_libmpv, True)
        self.assertIn("shinchiro", output)

    def test_linux_libmpv_plan_prefers_package_manager(self):
        with mock.patch("install._mpv_present", return_value=False), \
             mock.patch.object(platform_paths, "IS_WINDOWS", False), \
             mock.patch.object(platform_paths, "IS_LINUX", True), \
             mock.patch("install._package_manager", return_value="dnf"):
            _, output = _silent(install.do_libmpv, True)
        self.assertIn("dnf", output)
        self.assertIn("mpv-libs", output)


class PulseaudioUtilsTest(unittest.TestCase):
    """pactl -- فقط لینوکس؛ روی ویندوز باید بی‌صدا OK بده (بدون هیچ چک شبکه‌ای)."""

    def test_windows_is_a_noop(self):
        with mock.patch.object(platform_paths, "IS_WINDOWS", True), \
             mock.patch("shutil.which", side_effect=_network_should_not_be_called):
            status, output = _silent(install.do_pulseaudio_utils, False)
        self.assertEqual(status, install.Status.OK)

    def test_linux_pactl_already_present_is_ok(self):
        with mock.patch.object(platform_paths, "IS_WINDOWS", False), \
             mock.patch("shutil.which", return_value="/usr/bin/pactl"):
            status, _ = _silent(install.do_pulseaudio_utils, False)
        self.assertEqual(status, install.Status.OK)

    def test_linux_dry_run_plans_apt_install(self):
        with mock.patch.object(platform_paths, "IS_WINDOWS", False), \
             mock.patch("shutil.which", return_value=None), \
             mock.patch("install._package_manager", return_value="apt"):
            status, output = _silent(install.do_pulseaudio_utils, True)
        self.assertEqual(status, install.Status.PLANNED)
        self.assertIn("pulseaudio-utils", output)

    def test_linux_without_package_manager_is_manual(self):
        with mock.patch.object(platform_paths, "IS_WINDOWS", False), \
             mock.patch("shutil.which", return_value=None), \
             mock.patch("install._package_manager", return_value=None):
            status, output = _silent(install.do_pulseaudio_utils, False)
        self.assertEqual(status, install.Status.MANUAL)
        self.assertIn("pulseaudio-utils", output)


class TeamTalkManualStepsTest(unittest.TestCase):

    def test_linux_missing_sdk_prints_manual_bearware_steps(self):
        with mock.patch.object(platform_paths, "find_native_component", return_value=None), \
             mock.patch.object(platform_paths, "IS_WINDOWS", False):
            status, output = _silent(install.do_teamtalk, False)
        self.assertEqual(status, install.Status.MANUAL)
        self.assertIn("bearware.dk", output)
        self.assertIn("libTeamTalk5.so", output)

    def test_present_sdk_is_ok_and_prints_no_manual_steps(self):
        with mock.patch.object(platform_paths, "find_native_component", return_value=r"C:\ttbot\teamtalk\TeamTalk5.dll"):
            status, output = _silent(install.do_teamtalk, False)
        self.assertEqual(status, install.Status.OK)
        self.assertNotIn("bearware.dk", output)


class LibmpvWindowsAssetPatternTest(unittest.TestCase):
    """اسمِ asset شینچیرو تاریخ/کامیت داره؛ نسخه‌ی v3 (نیازمند AVX2) رد بشه."""

    def test_matches_plain_x86_64_build(self):
        self.assertTrue(install.LIBMPV_WINDOWS_ASSET_PATTERN.search("mpv-dev-x86_64-20260903-git-69e63f425a.7z"))

    def test_rejects_v3_variant(self):
        self.assertFalse(install.LIBMPV_WINDOWS_ASSET_PATTERN.search("mpv-dev-x86_64-v3-20260903-git-69e63f425a.7z"))

    def test_rejects_other_architectures(self):
        self.assertFalse(install.LIBMPV_WINDOWS_ASSET_PATTERN.search("mpv-dev-i686-20260903-git-69e63f425a.7z"))

    def test_pick_asset_finds_the_right_one_in_a_full_release(self):
        release = {"assets": [
            {"name": "mpv-dev-aarch64-20260903-git-69e63f425a.7z", "browser_download_url": "wrong-1"},
            {"name": "mpv-dev-x86_64-v3-20260903-git-69e63f425a.7z", "browser_download_url": "wrong-2"},
            {"name": "mpv-dev-x86_64-20260903-git-69e63f425a.7z", "browser_download_url": "right"},
        ]}
        asset = install._pick_asset(release, install.LIBMPV_WINDOWS_ASSET_PATTERN)
        self.assertEqual(asset["browser_download_url"], "right")


class SevenZipFallbackTest(unittest.TestCase):
    """stdlib نمی‌تونه 7z رو باز کنه؛ بدون ابزار 7z روی سیستم باید MANUAL بده، نه کرش."""

    def test_extract_7z_returns_none_without_a_tool(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(install._extract_7z("whatever.7z", tempfile.mkdtemp()))

    def test_windows_libmpv_install_is_manual_without_7z_tool(self):
        fake_release = {"assets": [
            {"name": "mpv-dev-x86_64-20260903-git-abc.7z", "browser_download_url": "https://example.invalid/mpv.7z"},
        ]}
        with mock.patch.object(platform_paths, "IS_WINDOWS", True), \
             mock.patch.object(platform_paths, "IS_LINUX", False), \
             mock.patch("install._mpv_present", return_value=False), \
             mock.patch("install._http_get_json", return_value=fake_release), \
             mock.patch("install._download", return_value="ignored"), \
             mock.patch("shutil.which", return_value=None):
            status, output = _silent(install.do_libmpv, False)
        self.assertEqual(status, install.Status.MANUAL)
        self.assertIn("7z", output)


class ArchiveExtractionSafetyTest(unittest.TestCase):

    def test_extracts_a_normal_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "a.zip")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("sub/file.txt", "hello")
            dest = os.path.join(tmp, "out")
            install._extract_archive(archive, dest)
            self.assertTrue(os.path.isfile(os.path.join(dest, "sub", "file.txt")))

    def test_path_traversal_member_is_not_written_outside_dest(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "evil.zip")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../../evil.txt", "pwn")
                zf.writestr("safe.txt", "ok")
            dest = os.path.join(tmp, "out")
            install._extract_archive(archive, dest)
            self.assertTrue(os.path.isfile(os.path.join(dest, "safe.txt")))
            leaked = os.path.join(tmp, "evil.txt")
            self.assertFalse(os.path.isfile(leaked))

    def test_find_in_tree_locates_nested_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = os.path.join(tmp, "a", "b", "c")
            os.makedirs(nested)
            open(os.path.join(nested, "target.bin"), "w").close()
            found = install._find_in_tree(tmp, "target.bin")
            self.assertEqual(found, os.path.join(nested, "target.bin"))

    def test_find_in_tree_returns_none_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(install._find_in_tree(tmp, "nope.bin"))


class JsRuntimeInstallTest(unittest.TestCase):

    def test_already_satisfied_is_a_noop(self):
        with mock.patch.object(platform_paths, "js_runtime", return_value={"node": {"path": "/usr/bin/node"}}), \
             mock.patch("install._download", side_effect=_network_should_not_be_called):
            status, output = _silent(install.do_js_runtime, False)
        self.assertEqual(status, install.Status.OK)
        self.assertIn("node", output)

    def test_dry_run_plan_mentions_deno_url_for_platform(self):
        with mock.patch.object(platform_paths, "js_runtime", return_value={}), \
             mock.patch.object(platform_paths, "IS_WINDOWS", False), \
             mock.patch.object(platform_paths, "IS_LINUX", True):
            status, output = _silent(install.do_js_runtime, True)
        self.assertEqual(status, install.Status.PLANNED)
        self.assertIn("deno-x86_64-unknown-linux-gnu.zip", output)


class TesseractComponentTest(unittest.TestCase):
    """
    tesseract (موتور OCR بررسی رسید): اختیاریه، مثل xray فقط با انتخاب
    صریح نصب می‌شه، ولی مقصدش هم باید از همون رجیستریِ core.platform_paths
    بیاد -- نه یه لیست مسیر جدا.
    """

    def test_optional_not_default(self):
        self.assertNotIn("tesseract", install.DEFAULT_COMPONENTS)
        self.assertIn("tesseract", install.ALL_COMPONENTS)

    def test_registered_in_platform_paths_native_components(self):
        self.assertIn("tesseract", platform_paths.NATIVE_COMPONENTS)

    def test_already_present_is_a_noop(self):
        with mock.patch.object(platform_paths, "has_tesseract", return_value=True), \
             mock.patch.object(platform_paths, "tesseract_binary", return_value="/usr/bin/tesseract"), \
             mock.patch("install._download", side_effect=_network_should_not_be_called), \
             mock.patch("install._http_get_json", side_effect=_network_should_not_be_called), \
             mock.patch("subprocess.run", side_effect=AssertionError("نباید هیچ دستوری اجرا بشه")):
            status, output = _silent(install.do_tesseract, False)
        self.assertEqual(status, install.Status.OK)
        self.assertIn("tesseract", output)

    def test_second_run_is_still_a_noop(self):
        with mock.patch.object(platform_paths, "has_tesseract", return_value=True), \
             mock.patch.object(platform_paths, "tesseract_binary", return_value="/usr/bin/tesseract"), \
             mock.patch("install._download", side_effect=_network_should_not_be_called):
            first, _ = _silent(install.do_tesseract, False)
            second, _ = _silent(install.do_tesseract, False)
        self.assertEqual(first, second)
        self.assertEqual(first, install.Status.OK)

    def test_linux_dry_run_plans_apt_with_persian_langpack(self):
        with mock.patch.object(platform_paths, "has_tesseract", return_value=False), \
             mock.patch.object(platform_paths, "IS_WINDOWS", False), \
             mock.patch.object(platform_paths, "IS_LINUX", True), \
             mock.patch("install._package_manager", return_value="apt"):
            status, output = _silent(install.do_tesseract, True)
        self.assertEqual(status, install.Status.PLANNED)
        self.assertIn("tesseract-ocr-fas", output)

    def test_linux_without_package_manager_is_manual(self):
        with mock.patch.object(platform_paths, "has_tesseract", return_value=False), \
             mock.patch.object(platform_paths, "IS_WINDOWS", False), \
             mock.patch.object(platform_paths, "IS_LINUX", True), \
             mock.patch("install._package_manager", return_value=None):
            status, output = _silent(install.do_tesseract, False)
        self.assertEqual(status, install.Status.MANUAL)
        self.assertIn("tesseract-ocr", output)

    def test_windows_dry_run_plan_mentions_ub_mannheim(self):
        with mock.patch.object(platform_paths, "has_tesseract", return_value=False), \
             mock.patch.object(platform_paths, "IS_WINDOWS", True), \
             mock.patch.object(platform_paths, "IS_LINUX", False):
            status, output = _silent(install.do_tesseract, True)
        self.assertEqual(status, install.Status.PLANNED)
        self.assertIn("UB-Mannheim", output)

    def test_windows_install_runs_silent_installer_with_dest_dir(self):
        fake_release = {"assets": [
            {"name": "tesseract-ocr-w64-setup-5.4.0.20240606.exe",
             "browser_download_url": "https://example.invalid/tesseract-setup.exe"},
        ]}
        with mock.patch.object(platform_paths, "has_tesseract", side_effect=[False, True]), \
             mock.patch.object(platform_paths, "tesseract_binary", return_value=r"C:\ttbot\tesseract\tesseract.exe"), \
             mock.patch.object(platform_paths, "IS_WINDOWS", True), \
             mock.patch.object(platform_paths, "IS_LINUX", False), \
             mock.patch("install._http_get_json", return_value=fake_release), \
             mock.patch("install._download", return_value="ignored") as download_mock, \
             mock.patch("subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(returncode=0)
            status, _ = _silent(install.do_tesseract, False)
        self.assertEqual(status, install.Status.DONE)
        download_mock.assert_called_once()
        args = run_mock.call_args[0][0]
        self.assertIn("/S", args)
        self.assertTrue(any(a.startswith("/D=") for a in args))

    def test_windows_asset_pattern_matches_versioned_installer(self):
        self.assertTrue(install.TESSERACT_WINDOWS_ASSET_PATTERN.search(
            "tesseract-ocr-w64-setup-5.4.0.20240606.exe"))


class ExitCodeTest(unittest.TestCase):

    def test_any_failure_gives_nonzero_exit(self):
        with mock.patch("install.do_ffmpeg", return_value=install.Status.FAILED), \
             mock.patch("install.do_teamtalk", return_value=install.Status.OK), \
             mock.patch("install.do_libmpv", return_value=install.Status.OK), \
             mock.patch("install.do_js_runtime", return_value=install.Status.OK), \
             mock.patch.object(install, "do_python", return_value=install.Status.OK):
            code, _ = _silent(install.main, [])
        self.assertEqual(code, 1)

    def test_manual_only_is_still_exit_zero(self):
        with mock.patch("install.do_ffmpeg", return_value=install.Status.OK), \
             mock.patch("install.do_teamtalk", return_value=install.Status.MANUAL), \
             mock.patch("install.do_libmpv", return_value=install.Status.OK), \
             mock.patch("install.do_js_runtime", return_value=install.Status.OK), \
             mock.patch.object(install, "do_python", return_value=install.Status.OK):
            code, output = _silent(install.main, [])
        self.assertEqual(code, 0)
        self.assertIn("کار دستی", output)


if __name__ == "__main__":
    unittest.main()
