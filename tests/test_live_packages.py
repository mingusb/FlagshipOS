"""Refuse altered package bytes and unrelated package changes during CAINE repair."""
import unittest
from flagship import live_packages


class LivePackageTests(unittest.TestCase):
    def test_incomplete_or_altered_package_is_rejected(self):
        for data in (b'', b'x' * live_packages.SIZE, b'x' * (live_packages.SIZE + 1)):
            with self.subTest(size=len(data)), self.assertRaises(RuntimeError):
                live_packages.verify_package(data)

    def test_only_the_expected_single_package_upgrade_is_allowed(self):
        live_packages.verify_plan('Reading package lists...\nInst wasta-remastersys [old] (new local-deb [all])\nConf wasta-remastersys (new local-deb [all])\n')
        for plan in ('', 'Inst wasta-remastersys\nInst libc6\n',
                     'Inst wasta-remastersys\nRemv bash\n', 'Inst different-package\n'):
            with self.subTest(plan=plan), self.assertRaises(RuntimeError):
                live_packages.verify_plan(plan)
