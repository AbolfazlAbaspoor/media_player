"""
Two classes of silent runtime breakage that are cheap to catch statically:
a missing or mismatched translation (one language crashes or shows a raw key),
and a catalog that names commands that no longer exist.
"""

import io
import json
import os
import re
import unittest

from licensing import catalog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACEHOLDER = re.compile(r"\{([a-zA-Z0-9_]+)\}")
CALL = re.compile(r"""i18n\.t\(\s*["']([a-zA-Z0-9_]+)["']""")


def load(path):
    data = json.load(io.open(os.path.join(ROOT, path), encoding="utf-8"))
    data = data.get("strings", data)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def referenced_keys(folders):
    keys = set()
    for folder in folders:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, folder)):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
            for name in filenames:
                if name.endswith(".py"):
                    text = io.open(os.path.join(dirpath, name), encoding="utf-8").read()
                    keys.update(CALL.findall(text))
    return keys


class TranslationTest(unittest.TestCase):

    PAIRS = [("languages/en.json", "languages/fa.json"),
             ("licensing/locales/en.json", "licensing/locales/fa.json")]

    def test_both_languages_have_the_same_keys(self):
        for en_path, fa_path in self.PAIRS:
            en, fa = load(en_path), load(fa_path)
            self.assertEqual(sorted(set(en) - set(fa)), [], fa_path + " is missing keys")
            self.assertEqual(sorted(set(fa) - set(en)), [], en_path + " is missing keys")

    def test_no_duplicate_keys_in_locale_files(self):
        for en_path, fa_path in self.PAIRS:
            for path in (en_path, fa_path):
                seen, dups = set(), []

                def hook(pairs):
                    for k, _ in pairs:
                        if k in seen:
                            dups.append(k)
                        seen.add(k)
                    return dict(pairs)
                json.load(io.open(os.path.join(ROOT, path), encoding="utf-8"),
                          object_pairs_hook=hook)
                self.assertEqual(dups, [], "duplicate keys in " + path)

    def test_placeholders_match_between_languages(self):
        for en_path, fa_path in self.PAIRS:
            en, fa = load(en_path), load(fa_path)
            bad = [k for k in set(en) & set(fa)
                   if set(PLACEHOLDER.findall(str(en[k]))) != set(PLACEHOLDER.findall(str(fa[k])))]
            self.assertEqual(sorted(bad), [], "placeholder mismatch in " + en_path)

    def test_every_key_used_in_code_exists(self):
        defined = set()
        for en_path, fa_path in self.PAIRS:
            defined |= set(load(en_path))
        used = referenced_keys(["commands", "core", "licensing"])
        bot_py = io.open(os.path.join(ROOT, "bot.py"), encoding="utf-8").read()
        used |= set(CALL.findall(bot_py))
        self.assertEqual(sorted(used - defined), [])


class CatalogTest(unittest.TestCase):

    def test_commands_named_in_features_exist_on_disk(self):
        on_disk = set()
        for name in os.listdir(os.path.join(ROOT, "commands")):
            if not name.endswith(".py") or name.startswith("_"):
                continue
            text = io.open(os.path.join(ROOT, "commands", name), encoding="utf-8").read()
            match = re.search(r"^NAME\s*=\s*(.+)$", text, re.M)
            if match:
                on_disk.update(re.findall(r"""["']([^"']+)["']""", match.group(1)))
        missing = []
        for code, feature in catalog.features().items():
            for command in feature.get("commands") or []:
                if command not in on_disk:
                    missing.append(f"{code}:{command}")
        self.assertEqual(missing, [])

    def test_every_capability_feature_provides_its_service(self):
        for code, service in catalog.CAPABILITY_OF_FEATURE.items():
            self.assertIn(service, catalog.features()[code]["services"], code)

    def test_youtube_is_base(self):
        self.assertIn("youtube", catalog.BASE_SERVICES)


if __name__ == "__main__":
    unittest.main()
