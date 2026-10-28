"""کمک‌های مشترک تست‌ها (به‌جای کپی‌کردنِ load_command توی هر فایل)."""

import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_command(name):
    """commands/<name>.py رو بدون ثبت توی sys.modules لود می‌کنه."""
    path = os.path.join(ROOT, "commands", name + ".py")
    spec = importlib.util.spec_from_file_location("cmd_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
