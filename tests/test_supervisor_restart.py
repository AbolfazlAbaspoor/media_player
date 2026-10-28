import types
import unittest

from licensing import supervisor as supervisor_module


class _FakeProcess:
    def __init__(self):
        self._alive = True
        self.pid = 4242
        self.returncode = None

    def poll(self):
        if self._alive:
            return None
        self.returncode = 0
        return 0

    def terminate(self):
        self._alive = False

    def kill(self):
        self._alive = False

    def wait(self, timeout=None):
        return 0


class _FakeDB:
    def __init__(self):
        self.updates = []

    def update_instance(self, instance_id, **fields):
        self.updates.append((instance_id, fields))

    def log_event(self, *a, **k):
        pass

    def runnable_instances(self):
        return []


class ShutdownDoesNotPersistStoppedTest(unittest.TestCase):
    """
    باگ: بستنِ کل سوپروایزر (Ctrl+C / ری‌استارت سرور) نباید نمونه‌ها رو
    توی دیتابیس 'stopped' علامت بزنه -- وگرنه دفعه‌ی بعد runnable_instances()
    اون‌ها رو نمی‌بینه و ربات‌ها خودکار بالا نمی‌آن (باید از تلگرام دستی
    استارت بشن).
    """

    def _managed_bot(self, sup, slug="bot1", instance_id=1):
        managed = supervisor_module._Managed(slug, instance_id)
        managed.process = _FakeProcess()
        sup._managed[slug] = managed
        return managed

    def test_shutdown_leaves_status_untouched(self):
        db = _FakeDB()
        sup = supervisor_module.Supervisor(db)
        self._managed_bot(sup)

        sup.shutdown(timeout=1)

        status_updates = [f for _, f in db.updates if "status" in f]
        self.assertEqual(status_updates, [], "shutdown must not persist status='stopped'")

    def test_explicit_stop_still_persists_stopped(self):
        db = _FakeDB()
        sup = supervisor_module.Supervisor(db)
        self._managed_bot(sup)

        sup.stop("bot1", timeout=1)

        status_updates = [f for _, f in db.updates if f.get("status") == "stopped"]
        self.assertEqual(len(status_updates), 1)


if __name__ == "__main__":
    unittest.main()
