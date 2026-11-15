"""Regression checks for lock drift and a contaminated baseline environment."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import check_python_lock as lock


class PythonLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in lock.INPUTS | {"ci/requirements-linux.lock", "ci/python-lock.json"}:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(lock.ROOT / name, target)
        self.metadata = json.loads((self.root / "ci/python-lock.json").read_text())

    def distributions(self, packages):
        return [SimpleNamespace(metadata={"Name": name}, version=version) for name, version in packages.items()]

    def test_current_source_inputs(self):
        self.assertTrue(lock.check(self.root)["inputs_validated"])

    def test_changed_upstream_requirements_are_rejected(self):
        with (self.root / "requirements.txt").open("a") as out:
            out.write("new-dependency\n")
        with self.assertRaisesRegex(ValueError, "stale Python lock input"):
            lock.check(self.root)

    def test_changed_wheel_hash_is_rejected(self):
        path = self.root / "ci/requirements-linux.lock"
        path.write_text(path.read_text().replace("sha256:", "sha256:0", 1))
        with self.assertRaisesRegex(ValueError, "digest does not match"):
            lock.check(self.root)

    def test_omitted_plugin_input_is_rejected(self):
        self.metadata["input_files"].pop("core/src/drivers/plugins/python/opcua/requirements.txt")
        (self.root / "ci/python-lock.json").write_text(json.dumps(self.metadata))
        with self.assertRaisesRegex(ValueError, "cover all runtime and plugin"):
            lock.check(self.root)

    def test_pins_and_bootstrap_pip_are_accepted(self):
        packages = {**self.metadata["packages"], "pip": "25.0.1"}
        with patch.object(lock.importlib.metadata, "distributions", return_value=self.distributions(packages)):
            result = lock.check(self.root, installed=True)
        self.assertTrue(result["installed_validated"])
        self.assertEqual(result["pip"], "25.0.1")

    def test_missing_extra_or_wrong_version_is_rejected(self):
        original = self.metadata["packages"]
        cases = [
            {name: version for name, version in original.items() if name != "flask"},
            {**original, "unexpected-package": "1.0"},
            {**original, "flask": "0.0"},
        ]
        for packages in cases:
            with self.subTest(packages=len(packages)), patch.object(lock.importlib.metadata, "distributions", return_value=self.distributions(packages)):
                with self.assertRaisesRegex(ValueError, "installed packages differ"):
                    lock.check(self.root, installed=True)


if __name__ == "__main__":
    unittest.main()
