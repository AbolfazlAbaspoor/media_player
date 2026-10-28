import threading
import time
import unittest

from core.trackqueue import TrackQueue


class NavRaceTest(unittest.TestCase):
    """
    باگ: دستورِ دستیِ n (ترد خودش) و تشخیصِ خودکارِ «آهنگ تموم شد» توی
    housekeeping (ترد حلقه‌ی اصلی) هیچ قفلِ مشترکی نداشتن، پس می‌تونستن
    هم‌زمان advance() رو صدا بزنن و صف دو قدم با هم جلو بره -- دو پیامِ
    Now playing پشتِ‌سرهم برای دو آیتمِ متوالی.
    """

    def _queue(self, items):
        q = TrackQueue(play_fn=lambda *a, **k: None)
        q.replace(items)
        return q

    def test_concurrent_advance_calls_never_corrupt_the_index(self):
        """
        دو تریگرِ *واقعاً مستقلِ* هم‌زمان (مثلاً n دستی درست همون لحظه‌ای که
        آهنگ طبیعی تموم شده) هرکدوم حق دارن یه قدم جلو ببرن -- دو قدمِ
        پشتِ‌سرهم این‌جا رفتارِ درسته، نه باگ. چیزی که _nav_lock تضمین
        می‌کنه اینه که این دو قدم *سریالی* و بدون خرابیِ وضعیت انجام بشه
        (نه این‌که یکی نصفه‌کاره‌ی دیگری رو بازنویسی کنه، ایندکس نامعتبر
        بشه، یا استثنا بندازه).
        """
        items = [{"url": f"http://x/{i}"} for i in range(5)]
        q = self._queue(items)
        self.assertEqual(q.index, 0)
        q._active = True  # شبیه‌سازیِ «آهنگِ اول در حال پخشه»

        barrier = threading.Barrier(2)
        errors = []

        def go(fn):
            barrier.wait(2)
            try:
                fn()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=go, args=(q.advance,))
        t2 = threading.Thread(target=go, args=(q.on_track_finished,))
        t1.start(); t2.start()
        t1.join(2); t2.join(2)

        self.assertEqual(errors, [])
        # هر دو تریگر واقعی بود، پس هر دو باید اعمال شده باشن: دقیقاً ۲ قدم.
        self.assertEqual(q.index, 2)

    def test_on_track_finished_does_not_block_when_manual_nav_holds_lock(self):
        q = self._queue([{"url": "http://x/0"}, {"url": "http://x/1"}])
        q._active = True
        started = threading.Event()
        release = threading.Event()

        def slow_play(url):
            started.set()
            release.wait(2)

        q._play = slow_play

        t = threading.Thread(target=q.advance)
        t.start()
        started.wait(2)

        # هم‌زمان با اینکه advance() دستی هنوز قفل رو داره، on_track_finished
        # نباید بلاک بشه -- فوراً (False, None) برمی‌گردونه.
        t0 = time.time()
        result = q.on_track_finished()
        elapsed = time.time() - t0
        self.assertEqual(result, (False, None))
        self.assertLess(elapsed, 0.5)

        release.set()
        t.join(2)

    def test_is_navigating_reflects_other_thread_holding_nav_lock(self):
        q = self._queue([{"url": "http://x/0"}, {"url": "http://x/1"}])
        self.assertFalse(q.is_navigating)

        started = threading.Event()
        release = threading.Event()

        def slow_play(url):
            started.set()
            release.wait(2)

        q._play = slow_play
        q._active = True
        t = threading.Thread(target=q.advance)
        t.start()
        started.wait(2)

        self.assertTrue(q.is_navigating)
        release.set()
        t.join(2)
        self.assertFalse(q.is_navigating)


if __name__ == "__main__":
    unittest.main()
