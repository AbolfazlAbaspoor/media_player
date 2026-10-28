"""
E-part2: تست‌های جدولیِ آفلاین برای هر رپرِ جدیدی که روی core/mpv/player.py
اضافه شده (پوشش کامل core/mpv/mpv.py).

هیچ‌جای این فایل libmpv واقعی لود نمی‌شه: قبل از import کردنِ mpv.player،
یه ماژول جعلیِ mpv.mpv توی sys.modules می‌ذاریم (چون player.py با
``from .mpv import MPV`` بهش وابسته‌ست) و خودِ Player هم هیچ‌وقت با
Player(...) واقعی ساخته نمی‌شه -- فقط Player.__new__(Player) و بعد یه
FakeRawMPV دستی به self.raw وصل می‌شه.
"""

import sys
import types
import unittest
from unittest import mock


def _install_fake_mpv_module():
    """
    یه ماژول جعلی به اسم mpv.mpv توی sys.modules می‌ذاره تا
    ``from .mpv import MPV`` توی player.py هیچ‌وقت فایل واقعیِ mpv.py (که
    لحظه‌ی import سعی می‌کنه libmpv رو با ctypes لود کنه) رو اجرا نکنه.
    """
    if "core.mpv.mpv" in sys.modules and getattr(sys.modules["core.mpv.mpv"], "_is_test_stub", False):
        return

    stub = types.ModuleType("core.mpv.mpv")
    stub._is_test_stub = True

    class MPV:  # pragma: no cover - این تست‌ها هیچ‌وقت این رو صدا نمی‌زنن
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "real mpv.mpv.MPV must never be constructed in offline tests; "
                "use Player.__new__(Player) + a fake raw object instead."
            )

    stub.MPV = MPV
    sys.modules["core.mpv.mpv"] = stub


_install_fake_mpv_module()

from core.mpv.player import Player  # noqa: E402  (باید بعد از stub بیاد)


class FakeRawMPV(mock.MagicMock):
    """
    جایگزینِ کامل و آفلاینِ شیء خامِ python-mpv (self.raw). چون خودِ
    MPV هم متد صدا می‌زنه (raw.command(...)) و هم پراپرتی می‌خونه/می‌نویسه
    (raw.pause, raw.volume = 50, ...)، یه MagicMock معمولی -- که هم
    call می‌شه هم attribute دلخواه می‌گیره/برمی‌گردونه -- دقیقاً همون رفتار
    رو بدون نیاز به تعریف دستیِ ده‌ها متد شبیه‌سازی می‌کنه.
    """


def make_player():
    """یه Player می‌سازه بدون صدازدنِ __init__ (که MPV واقعی رو می‌سازه)."""
    player = Player.__new__(Player)
    player.raw = FakeRawMPV()
    return player


class DelegationTableTest(unittest.TestCase):
    """
    هر ردیف: (توضیح، تابعی که رو player صدا می‌زنه، اسم متدِ raw، آرگومان‌های
    منتظره‌ی positional، آرگومان‌های منتظره‌ی keyword).
    تابع اجرا می‌شه، بعد چک می‌کنیم دقیقاً همون متدِ raw با همون آرگومان‌ها
    صدا زده شده باشه.
    """

    def _check(self, call, raw_attr, expect_args=(), expect_kwargs=None):
        player = make_player()
        call(player)
        mock_attr = getattr(player.raw, raw_attr)
        mock_attr.assert_called_once_with(*expect_args, **(expect_kwargs or {}))

    def test_delegation_table(self):
        table = [
            ("run_command", lambda p: p.run_command("foo", 1, bar=2), "command", ("foo", 1), {"bar": 2}),
            ("run_command_string", lambda p: p.run_command_string("foo", "a"), "string_command", ("foo", "a"), {}),
            (
                "run_command_async",
                lambda p: p.run_command_async("foo", 1, callback="cb"),
                "command_async",
                ("foo", 1),
                {"callback": "cb"},
            ),
            ("run_node_command", lambda p: p.run_node_command("foo", 1), "node_command", ("foo", 1), {}),
            ("run_subprocess", lambda p: p.run_subprocess("echo", "hi"), "run", ("echo", "hi"), {}),
            ("quit", lambda p: p.quit(5), "quit", (5,), {}),
            ("quit_and_save_position", lambda p: p.quit_and_save_position(2), "quit_watch_later", (2,), {}),
            ("set_log_level", lambda p: p.set_log_level("debug"), "set_loglevel", ("debug",), {}),
            ("revert_seek", lambda p: p.revert_seek(), "revert_seek", (), {}),
            ("step_frame_forward", lambda p: p.step_frame_forward(), "frame_step", (), {}),
            ("step_frame_backward", lambda p: p.step_frame_backward(), "frame_back_step", (), {}),
            ("adjust_property", lambda p: p.adjust_property("volume", 3), "property_add", ("volume", 3), {}),
            ("multiply_property", lambda p: p.multiply_property("speed", 2), "property_multiply", ("speed", 2), {}),
            ("cycle_property", lambda p: p.cycle_property("mute", "down"), "cycle", ("mute", "down"), {}),
            ("get_option_info", lambda p: p.get_option_info("volume"), "option_info", ("volume",), {}),
            (
                "load_file",
                lambda p: p.load_file("a.mp3", mode="append", index=1, start="10"),
                "loadfile",
                ("a.mp3", "append", 1),
                {"start": "10"},
            ),
            ("load_playlist_file", lambda p: p.load_playlist_file("a.m3u", mode="append"), "loadlist", ("a.m3u", "append"), {}),
            (
                "add_video_track",
                lambda p: p.add_video_track("v.mp4", title="t", language="en", albumart=True),
                "video_add",
                ("v.mp4",),
                {"title": "t", "lang": "en", "albumart": True},
            ),
            ("remove_video_track", lambda p: p.remove_video_track(3), "video_remove", (3,), {}),
            ("reload_video_track", lambda p: p.reload_video_track(3), "video_reload", (3,), {}),
            ("remove_audio_track", lambda p: p.remove_audio_track(2), "audio_remove", (2,), {}),
            ("reload_audio_track", lambda p: p.reload_audio_track(2), "audio_reload", (2,), {}),
            ("remove_subtitle", lambda p: p.remove_subtitle(1), "sub_remove", (1,), {}),
            ("reload_subtitle", lambda p: p.reload_subtitle(1), "sub_reload", (1,), {}),
            ("step_subtitle", lambda p: p.step_subtitle(-1), "sub_step", (-1,), {}),
            ("seek_subtitle", lambda p: p.seek_subtitle(1), "sub_seek", (1,), {}),
            ("toggle_osd", lambda p: p.toggle_osd(), "toggle_osd", (), {}),
            ("print_text", lambda p: p.print_text("hi"), "print_text", ("hi",), {}),
            ("show_text", lambda p: p.show_text("hi", "2000", 1), "show_text", ("hi", "2000", 1), {}),
            ("expand_text", lambda p: p.expand_text("${volume}"), "expand_text", ("${volume}",), {}),
            ("expand_path", lambda p: p.expand_path("~~/x"), "expand_path", ("~~/x",), {}),
            ("show_progress", lambda p: p.show_progress(), "show_progress", (), {}),
            ("rescan_external_files", lambda p: p.rescan_external_files("append"), "rescan_external_files", ("append",), {}),
            ("write_watch_later_config", lambda p: p.write_watch_later_config(), "write_watch_later_config", (), {}),
            ("send_discnav_command", lambda p: p.send_discnav_command("menu"), "discnav", ("menu",), {}),
            ("send_mouse_event", lambda p: p.send_mouse_event(1, 2, 0, "double"), "mouse", (1, 2, 0, "double"), {}),
            ("send_keypress", lambda p: p.send_keypress("q"), "keypress", ("q",), {}),
            ("send_keydown", lambda p: p.send_keydown("q"), "keydown", ("q",), {}),
            ("send_keyup", lambda p: p.send_keyup("q"), "keyup", ("q",), {}),
            ("bind_key_to_command", lambda p: p.bind_key_to_command("q", "quit"), "keybind", ("q", "quit"), {}),
            ("allocate_overlay_id", lambda p: p.allocate_overlay_id(), "allocate_overlay_id", (), {}),
            ("free_overlay_id", lambda p: p.free_overlay_id(3), "free_overlay_id", (3,), {}),
            (
                "create_file_overlay",
                lambda p: p.create_file_overlay("f.rgba", 100, 10, (1, 2)),
                "create_file_overlay",
                ("f.rgba", 100, 10, (1, 2)),
                {},
            ),
            ("create_image_overlay", lambda p: p.create_image_overlay("img", (1, 2)), "create_image_overlay", ("img", (1, 2)), {}),
            ("remove_overlay", lambda p: p.remove_overlay(4), "remove_overlay", (4,), {}),
            (
                "add_raw_overlay",
                lambda p: p.add_raw_overlay(1, 2, 3, "fd", 0, "bgra", 10, 10, 40),
                "overlay_add",
                (1, 2, 3, "fd", 0, "bgra", 10, 10, 40),
                {},
            ),
            ("remove_raw_overlay", lambda p: p.remove_raw_overlay(1), "overlay_remove", (1,), {}),
            (
                "set_osd_overlay",
                lambda p: p.set_osd_overlay(1, "{}", res_x=1, res_y=2, z=3, hidden=True),
                "osd_overlay",
                (1, "{}"),
                {"res_x": 1, "res_y": 2, "z": 3, "hidden": True},
            ),
            ("clear_osd_overlay", lambda p: p.clear_osd_overlay(1), "osd_overlay_remove", (1,), {}),
            ("send_script_message", lambda p: p.send_script_message("a", "b"), "script_message", ("a", "b"), {}),
            (
                "send_script_message_to",
                lambda p: p.send_script_message_to("target", "a"),
                "script_message_to",
                ("target", "a"),
                {},
            ),
            ("drop_buffers", lambda p: p.drop_buffers(), "drop_buffers", (), {}),
            (
                "run_video_filter_command",
                lambda p: p.run_video_filter_command("@l", "cmd", "arg"),
                "vf_command",
                ("@l", "cmd", "arg"),
                {},
            ),
            (
                "run_audio_filter_command",
                lambda p: p.run_audio_filter_command("@l", "cmd", "arg"),
                "af_command",
                ("@l", "cmd", "arg"),
                {},
            ),
            ("property_observer", lambda p: p.property_observer("volume"), "property_observer", ("volume",), {}),
            (
                "remove_property_observer",
                lambda p: p.remove_property_observer("volume", "handler"),
                "unobserve_property",
                ("volume", "handler"),
                {},
            ),
            (
                "remove_all_property_observers",
                lambda p: p.remove_all_property_observers("handler"),
                "unobserve_all_properties",
                ("handler",),
                {},
            ),
            (
                "register_script_message_handler",
                lambda p: p.register_script_message_handler("t", "handler"),
                "register_message_handler",
                ("t", "handler"),
                {},
            ),
            (
                "unregister_script_message_handler",
                lambda p: p.unregister_script_message_handler("t"),
                "unregister_message_handler",
                ("t",),
                {},
            ),
            ("script_message_handler", lambda p: p.script_message_handler("t"), "message_handler", ("t",), {}),
            ("add_event_callback", lambda p: p.add_event_callback("cb"), "register_event_callback", ("cb",), {}),
            ("remove_event_callback", lambda p: p.remove_event_callback("cb"), "unregister_event_callback", ("cb",), {}),
            (
                "bind_key_press",
                lambda p: p.bind_key_press("q", mode="force", repetition=True),
                "on_key_press",
                ("q", "force", True),
                {},
            ),
            ("bind_key", lambda p: p.bind_key("q", mode="default"), "key_binding", ("q", "default"), {}),
            (
                "register_key_callback",
                lambda p: p.register_key_callback("q", "quit", mode="force"),
                "register_key_binding",
                ("q", "quit", "force"),
                {},
            ),
            ("unbind_key", lambda p: p.unbind_key("q"), "unregister_key_binding", ("q",), {}),
            (
                "register_stream_protocol",
                lambda p: p.register_stream_protocol("foo", "open_fn"),
                "register_stream_protocol",
                ("foo", "open_fn"),
                {},
            ),
            (
                "register_python_stream",
                lambda p: p.register_python_stream("name", 10),
                "python_stream",
                ("name", 10),
                {},
            ),
            ("set_stream_catchall", lambda p: p.set_stream_catchall("cb"), "python_stream_catchall", ("cb",), {}),
            ("stream_writer", lambda p: p.stream_writer(), "play_context", (), {}),
            ("play_bytes", lambda p: p.play_bytes(b"data"), "play_bytes", (b"data",), {}),
            ("wait_until_paused", lambda p: p.wait_until_paused(timeout=5), "wait_until_paused", (), {"timeout": 5}),
            ("wait_for_playback_start", lambda p: p.wait_for_playback_start(timeout=5), "wait_until_playing", (), {"timeout": 5}),
            ("wait_for_shutdown", lambda p: p.wait_for_shutdown(timeout=1), "wait_for_shutdown", (), {"timeout": 1}),
        ]

        for name, call, raw_attr, expect_args, expect_kwargs in table:
            with self.subTest(wrapper=name):
                self._check(call, raw_attr, expect_args, expect_kwargs)

    def test_wait_for_property_without_cond(self):
        player = make_player()
        player.wait_for_property("idle-active", timeout=3)
        player.raw.wait_for_property.assert_called_once_with("idle-active", timeout=3)

    def test_wait_for_property_with_cond(self):
        player = make_player()
        cond = lambda v: v
        player.wait_for_property("idle-active", cond=cond, timeout=3)
        player.raw.wait_for_property.assert_called_once_with("idle-active", cond=cond, timeout=3)

    def test_wait_for_property_context_passthrough(self):
        player = make_player()
        result = player.wait_for_property_context("idle-active", timeout=2)
        player.raw.prepare_and_wait_for_property.assert_called_once_with("idle-active", timeout=2)
        self.assertIs(result, player.raw.prepare_and_wait_for_property.return_value)

    def test_wait_for_event_context_passthrough(self):
        player = make_player()
        result = player.wait_for_event_context("seek", "end-file", timeout=2)
        player.raw.prepare_and_wait_for_event.assert_called_once_with("seek", "end-file", timeout=2)
        self.assertIs(result, player.raw.prepare_and_wait_for_event.return_value)

    def test_is_core_alive_true_when_check_does_not_raise(self):
        player = make_player()
        player.raw.check_core_alive.return_value = None
        self.assertTrue(player.is_core_alive())
        player.raw.check_core_alive.assert_called_once_with()

    def test_is_core_alive_false_when_check_raises(self):
        player = make_player()
        player.raw.check_core_alive.side_effect = RuntimeError("shutdown")
        self.assertFalse(player.is_core_alive())

    def test_generic_get_property_translates_dashes(self):
        player = make_player()
        player.raw.time_pos = 12.5
        self.assertEqual(player.get_property("time-pos"), 12.5)

    def test_generic_set_property_translates_dashes(self):
        player = make_player()
        player.set_property("ao-volume", 42)
        self.assertEqual(player.raw.ao_volume, 42)

    def test_take_screenshot_image_passthrough(self):
        player = make_player()
        result = player.take_screenshot_image(include_subtitles=False)
        player.raw.screenshot_raw.assert_called_once_with(includes="video")
        self.assertIs(result, player.raw.screenshot_raw.return_value)

    def test_is_core_shutdown_property(self):
        player = make_player()
        player.raw.core_shutdown = True
        self.assertTrue(player.is_core_shutdown)

    def test_queue_filenames_property(self):
        player = make_player()
        player.raw.playlist_filenames = ["a.mp3", "b.mp3"]
        self.assertEqual(player.queue_filenames, ["a.mp3", "b.mp3"])

    def test_quit_swallows_raw_exceptions(self):
        player = make_player()
        player.raw.quit.side_effect = RuntimeError("boom")
        player.quit()  # نباید exception بندازه بیرون

    def test_unbind_key_swallows_raw_exceptions(self):
        player = make_player()
        player.raw.unregister_key_binding.side_effect = RuntimeError("boom")
        player.unbind_key("q")  # نباید exception بندازه بیرون


if __name__ == "__main__":
    unittest.main()
