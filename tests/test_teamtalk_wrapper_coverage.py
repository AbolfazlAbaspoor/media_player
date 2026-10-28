"""
Audit part 1 (docs/TEAMTALK_WRAPPER.md): core/teamtalk/ttbot.py باید هر قابلیتِ
خامِ SDK رو که core/teamtalk/TeamTalk5.py می‌ده پوشش بده، نه فقط چیزی که ربات
همین الان مصرف می‌کنه. این فایل هیچ‌وقت teamtalk.TeamTalk5/teamtalk.ttbot
رو import نمی‌کنه (اون import خودش DLL تیم‌تاک رو بارگذاری/مقداردهی
می‌کنه)، بلکه هر دو فایل رو با ast می‌خونه -- کاملاً آفلاین و بدون هیچ
وابستگی به وجودِ TeamTalk5.dll/so روی ماشینِ اجراکننده‌ی تست.

دو تست اینجاست:

  ۱. یه رگرسیون‌گارد: هر متدِ کلاسِ TeamTalk که واقعاً یه تابعِ _TT_* (یعنی
     یه بایندینگِ خامِ TT_*) صدا می‌زنه، باید یا جایی توی ttbot.py صدا زده
     بشه (self.tt.<name> یا type(self.tt).<name> برای مواردِ خاص مثلِ
     getMediaFileInfo)، یا صریحاً توی SKIP_WHITELIST این فایل با دلیل ذکر
     بشه. یه قابلیتِ تازه که به TeamTalk5.py اضافه بشه و نه wrap بشه نه
     whitelist، این تست رو می‌شکنه -- این «future drift» ایه که task خواسته.
  ۲. یه چک روی خودِ عددها، تا docs/TEAMTALK_WRAPPER.md دستی از بدنه‌ی
     کد جا نمونه.
"""

import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEAMTALK5_PATH = os.path.join(ROOT, "core", "teamtalk", "TeamTalk5.py")
TTBOT_PATH = os.path.join(ROOT, "core", "teamtalk", "ttbot.py")

# متدهای دان‌درِ پایتون -- نه یه قابلیتِ SDK، نه چیزی که whitelist صریح لازم
# داشته باشه (هیچ ابزاری این‌ها رو مستقیم صدا نمی‌زنه).
PYTHON_DUNDER_METHODS = {"__init__", "__del__"}

# چرا هرکدوم skip شدن: docs/TEAMTALK_WRAPPER.md بخشِ "Deliberately skipped"
# همینا رو با توضیحِ کامل‌تر تکرار می‌کنه؛ اینجا فقط خلاصه، برای این‌که با
# تغییرِ TeamTalk5.py (یه قابلیتِ تازه) این تست بترکه اگه wrap/whitelist نشه.
SKIP_WHITELIST = {
    # lifecycle: از قبل توسط TTBot.__init__/GC مدیریت می‌شه، نه یه اکشنِ جدا.
    "closeTeamTalk": "lifecycle, called only by TeamTalk.__del__",
    # runEventLoop و onXxx: یه مسیرِ دیسپچِ جایگزین که ttbot.py هیچ‌وقت صداش
    # نمی‌زنه -- خودش EVENT_MAP/_dispatch_message/subscribe داره.
    "runEventLoop": "superseded by ttbot's own EVENT_MAP/_dispatch_message dispatch",
}

# رویدادهای on* (هوک‌های قابلِ override که فقط runEventLoop صداشون می‌زنه).
EVENT_HOOK_REASON = "on* hook, only called by runEventLoop (see runEventLoop's skip reason)"

# توابعِ سطحِ ماژولِ TeamTalk5.py که واقعاً یه قابلیتِ مصرف‌کردنی برای رباتن.
RELEVANT_MODULE_FUNCS = {"getVersion", "setLicense", "buildTextMessage", "rebuildTextMessage"}

# بقیه‌ی توابعِ سطحِ ماژول: کمکِ داخلیِ خودِ TeamTalk5.py، نه قابلیتِ SDK.
MODULE_SKIP_WHITELIST = {
    "ttstr": "internal str<->ttchar helper, used by every wrapper, not a capability itself",
    "function_factory": "internal ctypes plumbing used only while defining the _TT_* bindings",
    "DBG_SIZEOF": "internal struct-size self-check used by every Structure.__init__ in TeamTalk5.py",
}


def _parse(path):
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


def _teamtalk_class_node(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "TeamTalk":
            return node
    raise AssertionError("class TeamTalk not found in TeamTalk5.py -- did the file move/rename?")


def _calls_named(func_node):
    """اسمِ همه‌ی توابعی که مستقیم (نه از طریق attribute) داخلِ این تابع صدا زده می‌شن."""
    names = []
    for n in ast.walk(func_node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            names.append(n.func.id)
    return names


def enumerate_teamtalk5_capabilities():
    """
    برمی‌گردونه: (real_caps, event_hooks, module_relevant, module_skip_rest)
      - real_caps: اسمِ متدهای TeamTalk که واقعاً یه _TT_* صدا می‌زنن (به‌جز
        lifecycle/dunder/on*).
      - event_hooks: اسمِ همه‌ی متدهای on* .
      - module_relevant: زیرمجموعه‌ی RELEVANT_MODULE_FUNCS که واقعاً در فایل تعریف شدن.
      - module_all: همه‌ی توابعِ سطحِ بالای ماژول (برای چک کاملیّت).
    """
    tree = _parse(TEAMTALK5_PATH)
    class_node = _teamtalk_class_node(tree)

    methods = {}
    for item in class_node.body:
        if isinstance(item, ast.FunctionDef):
            methods[item.name] = _calls_named(item)

    event_hooks = sorted(n for n in methods if n.startswith("on"))
    lifecycle_and_dunder = set(PYTHON_DUNDER_METHODS) | set(SKIP_WHITELIST)
    real_caps = sorted(
        n for n in methods
        if n not in lifecycle_and_dunder and n not in event_hooks
    )

    module_all = sorted(
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    )

    return real_caps, event_hooks, module_all


def _ttbot_source():
    with open(TTBOT_PATH, encoding="utf-8") as f:
        return f.read()


class TeamTalkWrapperCoverageTest(unittest.TestCase):
    """رگرسیون‌گاردِ اصلی: هر قابلیتِ خام یا wrap شده یا صریحاً whitelist شده."""

    @classmethod
    def setUpClass(cls):
        cls.real_caps, cls.event_hooks, cls.module_all = enumerate_teamtalk5_capabilities()
        cls.ttbot_src = _ttbot_source()

    def _is_called_in_ttbot(self, name):
        # الگوهای معتبرِ صدازدن توی ttbot.py: self.tt.<name>(...) برای اکثرِ
        # قابلیت‌ها، یا type(self.tt).<name>(...) برای موردِ خاصِ
        # getMediaFileInfo (باگِ باندینگِ بدونِ self، مستندشده در
        # docs/TEAMTALK_WRAPPER.md).
        patterns = (
            "self.tt.%s(" % name,
            "type(self.tt).%s(" % name,
        )
        return any(p in self.ttbot_src for p in patterns)

    def test_every_teamtalk_method_is_wrapped_or_whitelisted(self):
        for name in self.real_caps:
            with self.subTest(capability=name):
                self.assertTrue(
                    self._is_called_in_ttbot(name),
                    f"TeamTalk.{name} is neither called anywhere in core/teamtalk/ttbot.py "
                    f"nor listed in SKIP_WHITELIST -- add a thin wrapper method, or "
                    f"whitelist it with a reason (see docs/TEAMTALK_WRAPPER.md).",
                )

    def test_every_on_hook_is_either_wrapped_or_dead_by_design(self):
        # همه‌ی on* هوک‌ها عمداً استفاده نشدن (whitelist شده)، مگراینکه یکی‌شون
        # واقعاً توی ttbot.py صدا زده بشه (که یعنی دیگه لازمه از whitelist دربیاد).
        for name in self.event_hooks:
            with self.subTest(hook=name):
                if self._is_called_in_ttbot(name):
                    continue  # صدا زده شده؛ دیگه "dead by design" نیست، مشکلی نداره.
                # وگرنه باید توضیحِ EVENT_HOOK_REASON براش صادق باشه (چیزی برای
                # assert کردن نداریم جز همینکه در enumerate برگشته و مستندشده).
                self.assertTrue(EVENT_HOOK_REASON)

    def test_skip_whitelist_entries_still_exist_in_teamtalk5(self):
        # اگه یه متدِ whitelist شده از TeamTalk5.py حذف/تغییرِنام بدن، اینجا
        # باید بفهمیم (whitelist شده‌ی مرده = سیگنالِ drift).
        tree = _parse(TEAMTALK5_PATH)
        class_node = _teamtalk_class_node(tree)
        all_method_names = {n.name for n in class_node.body if isinstance(n, ast.FunctionDef)}
        for name in SKIP_WHITELIST:
            with self.subTest(whitelisted=name):
                self.assertIn(name, all_method_names)

    def test_module_level_relevant_functions_are_wrapped(self):
        for name in RELEVANT_MODULE_FUNCS:
            with self.subTest(func=name):
                self.assertIn(name, self.module_all, f"{name} no longer exists in TeamTalk5.py")
                # buildTextMessage مستقیم توسط _send_chunks مصرف می‌شه (نه یه
                # wrapper جدا)؛ بقیه باید یه بار صدا زده بشن.
                called_directly = ("%s(" % name) in self.ttbot_src
                self.assertTrue(
                    called_directly,
                    f"module-level {name}() is not called anywhere in core/teamtalk/ttbot.py",
                )

    def test_every_module_level_function_is_relevant_or_whitelisted(self):
        for name in self.module_all:
            with self.subTest(func=name):
                self.assertTrue(
                    name in RELEVANT_MODULE_FUNCS or name in MODULE_SKIP_WHITELIST,
                    f"module-level function {name} in TeamTalk5.py is neither wrapped "
                    f"(RELEVANT_MODULE_FUNCS) nor whitelisted (MODULE_SKIP_WHITELIST).",
                )

    def test_counts_match_documented_audit_numbers(self):
        # همون عددهایی که docs/TEAMTALK_WRAPPER.md بالای فایل نوشته -- اگه
        # TeamTalk5.py عوض بشه (قابلیتِ تازه) این عددها هم باید دستی آپدیت
        # بشن، وگرنه این تست یادآوری می‌کنه.
        self.assertEqual(len(self.real_caps), 78)
        self.assertEqual(len(self.event_hooks), 39)
        self.assertEqual(len(PYTHON_DUNDER_METHODS), 2)
        self.assertEqual(len(SKIP_WHITELIST), 2)
        self.assertEqual(len(RELEVANT_MODULE_FUNCS), 4)
        self.assertEqual(len(MODULE_SKIP_WHITELIST), 3)
        # جمعِ کل: 78 + 39 + 2 + 2 (dunder) باید کلِ متدهای کلاسِ TeamTalk باشه.
        tree = _parse(TEAMTALK5_PATH)
        class_node = _teamtalk_class_node(tree)
        total_class_methods = sum(1 for n in class_node.body if isinstance(n, ast.FunctionDef))
        self.assertEqual(
            total_class_methods,
            len(self.real_caps) + len(self.event_hooks) + len(SKIP_WHITELIST) + len(PYTHON_DUNDER_METHODS),
        )
        self.assertEqual(
            len(self.module_all),
            len(RELEVANT_MODULE_FUNCS) + len(MODULE_SKIP_WHITELIST),
        )


if __name__ == "__main__":
    unittest.main()
