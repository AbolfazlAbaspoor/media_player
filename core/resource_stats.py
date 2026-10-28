"""
آمار مصرف منابع خودِ پروسه‌ی ربات (RSS، CPU، تعداد thread، مدت اجرا).

برای دستور ادمینی `res` و ابزار tools/loadtest.py. اگه psutil نصب باشه
ازش استفاده می‌شه؛ وگرنه fallback سبک با کتابخونه‌ی استاندارد (Linux: /proc،
ویندوز: ctypes) تا نبودنش هیچ قابلیتی رو نبره.
"""

import os
import sys
import threading
import time

try:
    import psutil
except ImportError:
    psutil = None


def _rss_bytes_fallback():
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/self/statm") as f:
                return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            return None
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class _Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]
            c = _Counters()
            c.cb = ctypes.sizeof(c)
            k32 = ctypes.WinDLL("kernel32")
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi")
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return int(c.WorkingSetSize)
        except Exception:
            return None
    return None


def snapshot(start_time=None, pid=None):
    """
    dict: rss_mb, cpu_percent, cpu_seconds, threads, uptime (ثانیه، یا None).
    cpu_percent میانگین از شروع پروسه‌ست (نه لحظه‌ای)، چون یه دستور یک‌باره
    نباید خودش برای اندازه‌گیری بخوابه یا thread نگه داره.
    pid=None یعنی همین پروسه؛ با pid دیگه فقط با psutil کار می‌کنه.
    """
    now = time.time()
    if psutil is not None:
        p = psutil.Process(pid) if pid else psutil.Process()
        with p.oneshot():
            rss = p.memory_info().rss
            cpu_seconds = sum(p.cpu_times()[:2])
            threads = p.num_threads()
            created = p.create_time()
    else:
        rss = _rss_bytes_fallback()
        cpu_seconds = time.process_time()
        threads = threading.active_count()
        created = start_time
    begin = start_time or created
    lifetime = (now - created) if created else None
    return {
        "rss_mb": round(rss / 1048576, 1) if rss else None,
        "cpu_seconds": round(cpu_seconds, 2),
        "cpu_percent": round(100 * cpu_seconds / lifetime, 2) if lifetime and lifetime > 0 else None,
        "threads": threads,
        "uptime": (now - begin) if begin else None,
    }
