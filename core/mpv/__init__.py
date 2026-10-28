# مثل core/teamtalk/__init__.py: mpv.py لحظه‌ی import، libmpv رو لود می‌کنه، پس
# آماده‌سازی مسیر باید قبل از اون انجام بشه.
from core import platform_paths as _platform_paths

_platform_paths.prepare_native_libraries()
