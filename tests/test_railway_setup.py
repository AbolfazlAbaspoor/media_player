"""توابع خالصِ deploy/railway_setup.py (بدون شبکه و بدون ورودی کاربر)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import railway_setup as rs  # noqa: E402


def _elf_header(machine):
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = 2          # 64-bit
    header[5] = 1          # little-endian
    header[18:20] = machine.to_bytes(2, "little")
    return bytes(header)


class RailwaySetupTests(unittest.TestCase):
    def _write(self, name, data):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name
        self.addCleanup(self._td.cleanup)

    def test_elf_check_accepts_only_linux_x86_64(self):
        self.assertTrue(rs.is_linux_x86_64_elf(self._write("ok.so", _elf_header(0x3E))))
        self.assertFalse(rs.is_linux_x86_64_elf(self._write("arm.so", _elf_header(0xB7))))
        self.assertFalse(rs.is_linux_x86_64_elf(self._write("win.dll", b"MZ" + bytes(64))))
        self.assertFalse(rs.is_linux_x86_64_elf(os.path.join(self.tmp, "missing.so")))

    def test_find_file_prefers_shallowest(self):
        self._write("a/b/c/libTeamTalk5.so", b"1")
        shallow = self._write("a/libTeamTalk5.so", b"2")
        self.assertEqual(rs.find_file(self.tmp, "libTeamTalk5.so"), shallow)
        self.assertIsNone(rs.find_file(self.tmp, "nope.so"))

    def test_secret_paths(self):
        for secret in ("data/licensing/config.json", "data/x/identity.json", "a/private.key",
                       "data/licensing/licensing.sqlite3", "token.txt", "railway-variables.env",
                       "errors/errors.log", "data\\licensing\\keys\\public.key"):
            self.assertTrue(rs.is_secret_path(secret), secret)
        for fine in ("core/teamtalk/libTeamTalk5.so", "Dockerfile", "docs/RAILWAY.md",
                     "licensing/config.py", "languages/fa.json"):
            self.assertFalse(rs.is_secret_path(fine), fine)

    def test_find_big_files(self):
        self._write("small.bin", b"x" * 10)
        self._write("big.bin", b"x" * 2048)
        found = rs.find_big_files(self.tmp, ["small.bin", "big.bin", "gone.bin"], limit=1024)
        self.assertEqual([p for p, _ in found], ["big.bin"])

    def test_variables_text_skips_empty_values(self):
        text = rs.build_variables_text({"A": "1", "B": "", "C": "3"})
        self.assertEqual(text, "A=1\nC=3\n")


if __name__ == "__main__":
    unittest.main()
