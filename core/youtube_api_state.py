"""
اگه کلید YouTube Data API توی کانفیگ باشه و فعال باشه، سرویس یوتیوب از یه
مسیر سریع‌تر برای جستجو استفاده می‌کنه (یه درخواست سبک API به‌جای جستجوی
کامل yt-dlp). اگه نباشه/غیرفعال باشه، مثل قبل فقط با yt-dlp کار می‌کنه.
"""

_state = {"enabled": False, "key": ""}

def configure(enabled: bool, key: str = ""):
    _state["enabled"] = bool(enabled)
    _state["key"] = key or ""

def get_api_key():
    if _state["enabled"] and _state["key"]:
        return _state["key"]
    return None
