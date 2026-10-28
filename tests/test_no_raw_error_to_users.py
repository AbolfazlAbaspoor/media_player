"""
اسکنر AST: هیچ کدی توی commands/، core/ و bot.py نباید متن یه exception رو
(str(e)، f"{e}"، error=e و ...) مستقیم به یه فراخوانیِ کاربرمحور بده. تنها
مسیر مجاز logging_setup.safe_error_text(e) ـه (که خطای کامل رو لاگ می‌کنه و
فقط یه پیام کوتاه و تمیز برمی‌گردونه)، یا استثناهای خودِ پروژه که پیامشون
از i18n ساخته می‌شه (IPTVError / DocumentaryError).
"""

import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SINKS = {"user_message", "channel_broadcast", "notify", "send_message",
          "reply_text", "reply", "answer", "edit_message_text", "send_reply"}
_SAFE_CALLS = {"safe_error_text", "log_exception"}
_CURATED = {"IPTVError", "DocumentaryError", "LiveDVRError"}
_EXTRA_FILES = ["bot.py"]


def _files():
    for folder in ("commands", "core"):
        base = os.path.join(ROOT, folder)
        for name in sorted(os.listdir(base)):
            if name.endswith(".py"):
                yield os.path.join(base, name)
    for name in _EXTRA_FILES:
        yield os.path.join(ROOT, name)


def _call_name(node):
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def _tainted_names(expr, tainted):
    """اسم‌های آلوده‌ای که بدون عبور از safe_error_text توی expr استفاده شدن."""
    found = set()

    def walk(n):
        if isinstance(n, ast.Call) and _call_name(n) in _SAFE_CALLS:
            return
        if isinstance(n, ast.Name) and n.id in tainted:
            found.add(n.id)
        for c in ast.iter_child_nodes(n):
            walk(c)

    walk(expr)
    return found


def _handler_type_names(handler):
    t = handler.type
    if t is None:
        return set()
    # اسم ماژول (documentary.X) حساب نمی‌شه؛ فقط اسم خودِ کلاس
    module_parts = {id(n.value) for n in ast.walk(t) if isinstance(n, ast.Attribute)}
    return {n.attr if isinstance(n, ast.Attribute) else n.id
            for n in ast.walk(t)
            if isinstance(n, ast.Attribute)
            or (isinstance(n, ast.Name) and id(n) not in module_parts)}


def find_leaks(source, filename="<src>"):
    leaks = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ExceptHandler) or not node.name:
            continue
        names = _handler_type_names(node)
        if names and names <= _CURATED:
            continue
        tainted = {node.name}
        # انتشار ساده‌ی آلودگی از طریق انتساب داخل خودِ handler
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Assign) and _tainted_names(stmt.value, tainted):
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name):
                        tainted.add(tgt.id)
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and _call_name(call) in _SINKS:
                for arg in list(call.args) + [k.value for k in call.keywords]:
                    if _tainted_names(arg, tainted):
                        leaks.append(f"{filename}:{call.lineno}")
    return leaks


class NoRawErrorToUsersTest(unittest.TestCase):

    def test_scanner_catches_leaks(self):
        bad = "try:\n pass\nexcept Exception as e:\n bot.t.user_message(1, str(e))\n"
        self.assertTrue(find_leaks(bad))
        bad2 = "try:\n pass\nexcept Exception as e:\n m = f'x {e}'\n notify(bot, c, 'k', error=m)\n"
        self.assertTrue(find_leaks(bad2))
        ok = "try:\n pass\nexcept Exception as e:\n notify(bot, c, 'k', error=safe_error_text(e))\n"
        self.assertFalse(find_leaks(ok))

    def test_no_command_or_core_leaks_exception_text(self):
        leaks = []
        for path in _files():
            with open(path, encoding="utf-8") as f:
                leaks += find_leaks(f.read(), os.path.relpath(path, ROOT))
        self.assertEqual(leaks, [], "exception text reaches a user-facing call")


class ChannelNoticeRoutingTest(unittest.TestCase):
    """
    خبرهایی که برای کل کانال معنی دارن (اسم کاربر توشونه) نباید خصوصی برن.

    queue_start (b.py) عمداً این‌جا نیست: برخلافِ آخرِ صف (که یعنی «وقتِ
    سرچِ تازه»، به‌درد بقیه‌ی کانال هم می‌خوره)، اولِ صف یه مرزِ کاملاً
    شخصیه و درخواستِ صریحِ مالک بود که خصوصی بره.
    """

    _CHANNEL_KEYS = ["search_ended", "queue_end",
                     "cookies_toggled", "ig_reels_refreshed"]

    def test_channel_notices_not_sent_privately(self):
        import re
        for name in ("n", "b", "ck", "rr"):
            with open(os.path.join(ROOT, "commands", name + ".py"), encoding="utf-8") as f:
                src = f.read()
            for key in self._CHANNEL_KEYS:
                self.assertFalse(
                    re.search(r"user_message\([^)]*[\"']%s[\"']" % key, src),
                    f"{name}.py sends {key} privately")


if __name__ == "__main__":
    unittest.main()
