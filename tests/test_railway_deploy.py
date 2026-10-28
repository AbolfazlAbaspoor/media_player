"""فایل‌های استقرار Railway سر جاشونن و سالم‌ان (بدون نیاز به داکر)."""
import json
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class RailwayDeployTests(unittest.TestCase):
    def test_railway_json_points_to_dockerfile(self):
        cfg = json.loads(_read("railway.json"))
        self.assertEqual(cfg["build"]["builder"], "DOCKERFILE")
        self.assertTrue(os.path.isfile(os.path.join(ROOT, cfg["build"]["dockerfilePath"])))

    def test_dockerfile_runs_only_the_license_server(self):
        dockerfile = _read("Dockerfile")
        self.assertIn("ENTRYPOINT", dockerfile)
        self.assertIn("exec python license_server.py", _read("docker", "start.sh"))
        # Railway از دستور VOLUME پشتیبانی نمی‌کنه (کامنت‌ها اشکال ندارن)
        code = [l for l in dockerfile.splitlines() if not l.lstrip().startswith("#")]
        self.assertFalse(any(l.strip().startswith("VOLUME") for l in code))

    def test_shell_scripts_have_valid_syntax(self):
        for name in ("entrypoint.sh", "start.sh"):
            path = os.path.join(ROOT, "docker", name)
            result = subprocess.run(["sh", "-n", path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_dockerignore_keeps_teamtalk_so_but_drops_windows_binaries(self):
        lines = [l.strip() for l in _read(".dockerignore").splitlines()]
        self.assertIn("**/*.dll", lines)
        self.assertIn("**/*.exe", lines)
        self.assertFalse(any(l.endswith(".so") for l in lines))
        self.assertIn("data/", lines)

    def test_gitignore_blocks_big_windows_binaries_not_the_so(self):
        text = _read(".gitignore")
        for pattern in ("*.dll", "*.exe", "tesseract/", "data/licensing/"):
            self.assertIn(pattern, text)
        rules = [l.strip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        self.assertFalse(any(r.endswith(".so") for r in rules))


if __name__ == "__main__":
    unittest.main()
