"""Verify catalog coverage and the distinction between images and imports."""

import importlib.resources
import json
import re
import unittest


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(
            importlib.resources.files("flagship").joinpath("profiles.json").read_text(encoding="utf-8")
        )
        cls.profiles = cls.catalog["profiles"]

    def test_seven_collections_have_distinct_profiles(self):
        self.assertEqual(
            set(self.profiles),
            {"kali", "parrot", "backbox", "remnux", "caine", "tsurugi", "sift"},
        )

    def test_registry_sources_are_immutable_not_floating_tags(self):
        registry = {key for key, profile in self.profiles.items() if profile["kind"] == "registry"}
        self.assertEqual(registry, {"kali", "parrot", "remnux"})
        for key in registry:
            with self.subTest(profile=key):
                self.assertRegex(self.profiles[key]["image"], r"^docker\.io/[^\s@]+@sha256:[a-f0-9]{64}$")

    def test_unverified_images_are_explicit_imports(self):
        imports = {key for key, profile in self.profiles.items() if profile["kind"] == "import"}
        self.assertEqual(imports, {"backbox", "caine", "tsurugi", "sift"})
        for key in imports:
            with self.subTest(profile=key):
                self.assertIsNone(self.profiles[key]["image"])
                self.assertIn("experimental", " ".join(self.profiles[key]["notes"]).lower())
                self.assertEqual(self.profiles[key]["packages"], [])

    def test_sources_and_smoke_commands_are_reviewable_data(self):
        for key, profile in self.profiles.items():
            with self.subTest(profile=key):
                self.assertTrue(profile["source_url"].startswith("https://"))
                self.assertTrue(profile["description"])
                self.assertTrue(profile["notes"])
                for command in profile["smoke_commands"]:
                    self.assertIsInstance(command, list)
                    self.assertGreater(len(command), 0)
                    self.assertTrue(all(isinstance(arg, str) and "\x00" not in arg for arg in command))
                for package in profile["packages"]:
                    self.assertIsNotNone(re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", package))

    def test_kali_toolkit_installation_is_explicit(self):
        self.assertEqual(self.profiles["kali"]["packages"], ["kali-linux-headless"])
        self.assertIn("not every Kali package", " ".join(self.profiles["kali"]["notes"]))


if __name__ == "__main__":
    unittest.main()
