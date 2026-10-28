"""
E-part2: تضمین می‌کنه که core/mpv/player.py *همیشه* هر قابلیت عمومیِ core/mpv/mpv.py
(کتابخونه‌ی خامِ python-mpv) رو پوشش بده -- یا صریحاً و با دلیل، skip شده
باشه (لیست SKIP_WHITELIST پایین، که باید با docs/MPV_WRAPPER.md هم‌خون
بمونه).

عمداً به‌جای import کردنِ mpv.py، از ast استفاده می‌کنیم: خودِ import
کردنِ اون فایل سعی می‌کنه libmpv واقعی رو با ctypes لود کنه، که دقیقاً
همون کاریه که تست‌های آفلاین نباید انجام بدن.
"""

import ast
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MPV_RAW_PATH = os.path.join(_ROOT, "core", "mpv", "mpv.py")
_PLAYER_PATH = os.path.join(_ROOT, "core", "mpv", "player.py")

# قابلیت‌های عمومیِ MPV که این رپر عمداً پوشش نمی‌ده، به‌همراه دلیل (باید با
# جدول "چیزی که عمداً skip شده" توی docs/MPV_WRAPPER.md یکی باشه).
SKIP_WHITELIST = {
    "properties": (
        "برای هر پراپرتیِ libmpv (چند صد تا) یه option_info جدا صدا می‌زنه؛ "
        "عملیات کند/سنگینیه که نباید یه راه راحت و یه‌خطی برای صدازدنِ "
        "تصادفی سرِ راه ربات داشته باشه. player.raw.properties همیشه در "
        "دسترسه."
    ),
}


def _get_decorator_names(node):
    names = []
    for d in node.decorator_list:
        if isinstance(d, ast.Name):
            names.append(d.id)
        elif isinstance(d, ast.Attribute):
            names.append(d.attr)
        elif isinstance(d, ast.Call):
            if isinstance(d.func, ast.Name):
                names.append(d.func.id)
            elif isinstance(d.func, ast.Attribute):
                names.append(d.func.attr)
    return names


def _find_class(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found")


def raw_public_capabilities():
    """
    برمی‌گردونه: مجموعه‌ی اسم هر متد/پراپرتیِ عمومیِ کلاس MPV توی core/mpv/mpv.py
    (بدون dunder ها، بدون _private، و بدون setter/getter/deleterهای اضافه‌ی
    یه پراپرتی که قبلاً شمرده شده).
    """
    with open(_MPV_RAW_PATH, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="mpv.py")

    class_node = _find_class(tree, "MPV")

    capabilities = set()
    for node in class_node.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name
        if name.startswith("_"):
            continue
        decs = _get_decorator_names(node)
        if "setter" in decs or "getter" in decs or "deleter" in decs:
            continue
        capabilities.add(name)
    return capabilities


def player_delegated_names():
    """
    برمی‌گردونه: مجموعه‌ی هر اسمی که Player توی player.py با
    self.raw.<name> بهش دسترسی داره (متد یا پراپرتی، فرقی نمی‌کنه)، به‌علاوه
    یه مارکر مخصوص وقتی دسترسیِ عمومی (getattr/setattr(self.raw, ...))
    استفاده شده باشه.
    """
    with open(_PLAYER_PATH, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="player.py")

    class_node = _find_class(tree, "Player")

    used = set()
    for node in ast.walk(class_node):
        if isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Attribute)
                and node.value.attr == "raw"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
            ):
                used.add(node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("getattr", "setattr"):
            if node.args and isinstance(node.args[0], ast.Attribute) and node.args[0].attr == "raw":
                used.add("<generic-property>")
    return used


class WrapperCoverageTest(unittest.TestCase):
    def test_every_raw_capability_is_wrapped_or_whitelisted(self):
        raw = raw_public_capabilities()
        used = player_delegated_names()

        missing = sorted(raw - used - set(SKIP_WHITELIST))
        self.assertEqual(
            missing,
            [],
            "این قابلیت‌های mpv.py نه توی player.py پوشش داده شدن نه توی "
            "SKIP_WHITELIST مستند شدن: %r" % (missing,),
        )

    def test_whitelist_entries_are_still_unwrapped(self):
        # اگه یه روزی یکی از این‌ها رو wrap کردیم ولی از whitelist حذفش
        # نکردیم، این تست بهمون یادآوری می‌کنه (whitelist نباید چیز مرده
        # نگه داره).
        used = player_delegated_names()
        stale = sorted(name for name in SKIP_WHITELIST if name in used)
        self.assertEqual(
            stale,
            [],
            "این‌ها توی SKIP_WHITELIST هستن ولی الان واقعاً wrap شدن؛ از "
            "whitelist و از docs/MPV_WRAPPER.md حذفشون کن: %r" % (stale,),
        )

    def test_whitelist_matches_docs(self):
        with open(os.path.join(_ROOT, "docs", "MPV_WRAPPER.md"), encoding="utf-8") as f:
            docs_text = f.read()
        for name in SKIP_WHITELIST:
            self.assertIn(
                f"`{name}`",
                docs_text,
                f"'{name}' توی SKIP_WHITELIST هست ولی توی docs/MPV_WRAPPER.md نیومده",
            )

    def test_raw_capability_count_is_tracked(self):
        # این عدد صرفاً یه یادآوریه: اگه mpv.py آپدیت بشه و این عدد عوض
        # بشه، یعنی یه قابلیت جدید/حذف‌شده هست که باید توی
        # docs/MPV_WRAPPER.md هم به‌روز بشه. تست بالا (coverage) قرمز شدنش
        # مهم‌تره؛ این فقط یه پرچم زودهنگامه.
        raw = raw_public_capabilities()
        self.assertEqual(
            len(raw),
            103,
            "تعداد قابلیت‌های عمومیِ MPV توی mpv.py عوض شده؛ "
            "docs/MPV_WRAPPER.md رو هم به‌روز کن.",
        )


if __name__ == "__main__":
    unittest.main()
