"""
یه کش کوچیک با دو تا سقف: عمر (TTL) و تعداد آیتم.

چرا لازمه: سرویس‌ها نتیجه‌ی سرچ و لیست کانال/آرتیست رو کش می‌کردن، ولی
کش لیست کانال‌ها (_channel_cache / _artist_cache) نه عمر داشت نه سقف
تعداد. روی رباتی که هفته‌ها بالاست، هر کانال/آرتیستی که یه بار باز شده
تا آخر عمر پروسه توی RAM می‌موند -- یعنی یه نشت حافظه‌ی آروم. اینجا هر دو
سقف اعمال می‌شن.

نکته: مقدارها موقع get کپی برمی‌گردن، چون صدا زننده‌ها (مثل دستور cv)
لیست برگشتی رو دستکاری/برش می‌زنن و نباید به نسخه‌ی داخل کش دست بخوره.
"""

import threading
import time


class TTLCache:
    def __init__(self, ttl=300, max_items=200):
        self.ttl = ttl
        self.max_items = max_items
        self._data = {}
        self._lock = threading.Lock()

    def get(self, key):
        """مقدار (کپی) یا None اگه نبود/منقضی شده بود."""
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            stored_at, value = entry
            if time.time() - stored_at > self.ttl:
                self._data.pop(key, None)
                return None
        return self._copy(value)

    def set(self, key, value):
        with self._lock:
            if key not in self._data and len(self._data) >= self.max_items:
                # قدیمی‌ترین آیتم قربانی می‌شه (LRU ساده بر اساس زمان درج).
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (time.time(), self._copy(value))

    def clear(self):
        with self._lock:
            self._data.clear()

    def __len__(self):
        with self._lock:
            return len(self._data)

    @staticmethod
    def _copy(value):
        if isinstance(value, list):
            return list(value)
        if isinstance(value, dict):
            return dict(value)
        return value
