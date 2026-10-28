import threading
import unittest

from core.trackqueue import TrackQueue


class GrowthRefreshTest(unittest.TestCase):
    def test_stale_growth_is_discarded_after_replace(self):
        gate = threading.Event()
        done = threading.Event()
        holder = {}

        calls = []

        def grow(needed):
            calls.append(1)
            if len(calls) == 1:  # فقط رشدِ صفِ قدیمی معطل می‌مونه
                gate.wait(5)
                return [{"url": "http://old/1", "title": "old"}]
            return []

        def submit(fn, *a):
            t = threading.Thread(target=lambda: (fn(*a), done.set()))
            holder.setdefault("all", []).append(t)
            t.start()

        q = TrackQueue(play_fn=lambda *a, **k: None, grow_fn=grow, submit_fn=submit)
        q.replace([{"url": "http://a/1", "title": "a"}])
        q.replace([{"url": "http://b/1", "title": "b"}])  # سرچ جدید
        gate.set()
        done.wait(5)
        for t in holder["all"]:
            t.join(5)
        self.assertEqual(q.length, 1)


if __name__ == "__main__":
    unittest.main()
