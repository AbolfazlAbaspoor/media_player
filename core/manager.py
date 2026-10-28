import importlib.util
import inspect
import os

from core import logging_setup
from core.paths import resource_dir

# مثل commands/: بعد از بیلد داخل باندله، ولی نسخه‌ی کنار برنامه برنده‌ست.
DEFAULT_SERVICES_DIR = resource_dir("core", "services")

class ServiceManager:
    """
    هر فایل .py داخل پوشه‌ی services یک "سرویس" است.
    هر سرویس باید یک کلاس داشته باشد که متد search(query) را پیاده‌سازی کرده باشد.
    خروجی search می‌تواند یک لینک (str) یا یک پلی‌لیست (list[str]) باشد.
    """

    def __init__(self, folder=None):
        # مسیر مطلق، نه نسبی: وگرنه اجرا از هر پوشه‌ای غیر از پوشه‌ی پروژه
        # (مثلاً از launcher.py) باعث می‌شه هیچ سرویسی پیدا/لود نشه.
        self.folder = folder or DEFAULT_SERVICES_DIR
        self.services = {}
        if not os.path.exists(self.folder):
            os.makedirs(self.folder)

    def _find_service_class(self, module):
        for attr_name, obj in vars(module).items():
            if not inspect.isclass(obj):
                continue
            if obj.__module__ != module.__name__:
                continue
            if hasattr(obj, "search") and callable(getattr(obj, "search")):
                return obj
        return None

    def load_services(self):
        self.services = {}
        if not os.path.isdir(self.folder):
            return self.services

        for filename in sorted(os.listdir(self.folder)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            module_name = filename[:-3]
            path = os.path.join(self.folder, filename)

            try:
                spec = importlib.util.spec_from_file_location(module_name, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                service_class = self._find_service_class(module)
                if service_class is None:
                    logging_setup.log_warning(f"No valid class (with a search method) found in '{filename}'.", context="loading services")
                    continue

                self.services[module_name] = service_class()
            except Exception:
                logging_setup.log_exception(f"loading service '{filename}'")
                continue

        return self.services


def searchable_service_names(services: dict) -> list:
    """
    فقط اسم سرویس‌هایی که سرچ متنی واقعی پشتیبانی می‌کنن (SUPPORTS_SEARCH
    غایب یا True) -- مثل youtube. سرویس‌های فقط-لینک (instagram, tiktok,
    soundcloud, spotify) که SUPPORTS_SEARCH=False دارن حذف می‌شن، چون
    دستور اختصاصی خودشون رو دارن (ir/tk/sc/spt) و جزو چرخه‌ی w/p نیستن.
    """
    return [name for name, svc in services.items() if getattr(svc, "SUPPORTS_SEARCH", True)]
