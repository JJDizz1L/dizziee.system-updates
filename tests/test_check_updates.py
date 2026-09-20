"""Tests for the mise source in scripts/check_updates.py.

Run with: python3 -m unittest discover -s tests
"""

import importlib.util
import json
import subprocess
import types
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_updates.py"
_spec = importlib.util.spec_from_file_location("check_updates", SCRIPT)
check_updates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_updates)


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class RunMiseOutdatedTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._real = check_updates.subprocess.run

        def fake_run(command, **kwargs):
            self.calls.append((command, kwargs))
            return self.responses.pop(0)

        self.responses = []
        check_updates.subprocess.run = fake_run
        self.addCleanup(lambda: setattr(check_updates.subprocess, "run", self._real))

    def test_parses_object(self):
        self.responses.append(completed(stdout='{"codex": {"current": "1"}}'))
        result = check_updates.run_mise_outdated("/usr/bin/mise", "0")
        self.assertEqual(list(result), ["codex"])

    def test_pins_query_to_home_and_sets_override(self):
        self.responses.append(completed(stdout="{}"))
        check_updates.run_mise_outdated("/usr/bin/mise", "0")
        _, kwargs = self.calls[0]
        self.assertEqual(kwargs["cwd"], check_updates.os.path.expanduser("~"))
        self.assertEqual(kwargs["env"]["MISE_MINIMUM_RELEASE_AGE"], "0")

    def test_omits_override_when_release_age_is_none(self):
        self.responses.append(completed(stdout="{}"))
        check_updates.run_mise_outdated("/usr/bin/mise", None)
        _, kwargs = self.calls[0]
        self.assertNotIn("MISE_MINIMUM_RELEASE_AGE", kwargs["env"])

    def test_rejects_nonzero_exit(self):
        self.responses.append(completed(stdout="{}", returncode=1))
        self.assertIsNone(check_updates.run_mise_outdated("/usr/bin/mise", "0"))

    def test_rejects_malformed_json(self):
        self.responses.append(completed(stdout="not json"))
        self.assertIsNone(check_updates.run_mise_outdated("/usr/bin/mise", "0"))

    def test_rejects_json_array(self):
        self.responses.append(completed(stdout="[]"))
        self.assertIsNone(check_updates.run_mise_outdated("/usr/bin/mise", "0"))

    def test_rejects_override_when_mise_reports_invalid_duration(self):
        # Some mise builds reject MISE_MINIMUM_RELEASE_AGE=0 with this warning,
        # print "{}", and still exit 0.
        self.responses.append(
            completed(
                stdout="{}",
                stderr="mise WARN Failed to resolve tool version list for codex: "
                "Invalid date or duration: 0",
            )
        )
        self.assertIsNone(check_updates.run_mise_outdated("/usr/bin/mise", "0"))

    def test_version_notice_on_stderr_is_not_a_rejection(self):
        self.responses.append(
            completed(stdout="{}", stderr="mise WARN mise version 2026.9.12 available")
        )
        self.assertEqual(check_updates.run_mise_outdated("/usr/bin/mise", "0"), {})


class CheckMiseTests(unittest.TestCase):
    def setUp(self):
        self._real = check_updates.run_mise_outdated
        self.calls = []

        def fake(binary, release_age):
            self.calls.append(release_age)
            return self.responses.pop(0)

        self.responses = []
        check_updates.run_mise_outdated = fake
        self.addCleanup(
            lambda: setattr(check_updates, "run_mise_outdated", self._real)
        )

    def test_no_binary_is_zero(self):
        self.assertEqual(check_updates.check_mise(None), 0)
        self.assertEqual(self.calls, [])

    def test_counts_outdated_tools(self):
        self.responses.append({"codex": {}, "claude": {}})
        self.assertEqual(check_updates.check_mise("/usr/bin/mise"), 2)
        self.assertEqual(self.calls, ["0"])

    def test_falls_back_without_override_when_rejected(self):
        self.responses.extend([None, {"codex": {}}])
        self.assertEqual(check_updates.check_mise("/usr/bin/mise"), 1)
        self.assertEqual(self.calls, ["0", None])

    def test_zero_when_everything_current(self):
        self.responses.append({})
        self.assertEqual(check_updates.check_mise("/usr/bin/mise"), 0)

    def test_zero_when_both_probes_fail(self):
        self.responses.extend([None, None])
        self.assertEqual(check_updates.check_mise("/usr/bin/mise"), 0)


class MiseToolCountTests(unittest.TestCase):
    def setUp(self):
        self._real = check_updates.subprocess.run
        self.addCleanup(lambda: setattr(check_updates.subprocess, "run", self._real))

    def _respond(self, response):
        check_updates.subprocess.run = lambda *a, **k: response

    def test_counts_configured_tools(self):
        self._respond(completed(stdout='{"node": [], "go": []}'))
        self.assertEqual(check_updates.mise_tool_count("/usr/bin/mise"), 2)

    def test_no_binary_is_zero(self):
        self.assertEqual(check_updates.mise_tool_count(None), 0)

    def test_failure_is_zero(self):
        self._respond(completed(stdout="{}", returncode=1))
        self.assertEqual(check_updates.mise_tool_count("/usr/bin/mise"), 0)


class MainIntegrationTests(unittest.TestCase):
    """main() must surface a mise row and include it in the total."""

    def setUp(self):
        self.patches = {}
        for name, value in {
            "aur_helper": lambda: None,
            "check_pacman": lambda: 3,
            "check_omarchy": lambda: 0,
            "check_mise": lambda binary: 2,
            "mise_binary": lambda: "/usr/bin/mise",
            "mise_tool_count": lambda binary: 8,
            "installed_pkg_names": lambda: set(),
            "omarchy_pkg_count": lambda installed: 0,
            "load_pkg_counts": lambda: None,
            "save_pkg_counts": lambda counts: self.saved.update(counts),
        }.items():
            self.patches[name] = getattr(check_updates, name)
            setattr(check_updates, name, value)
        self.saved = {}
        self.addCleanup(self._restore)
        self._real_which = check_updates.shutil.which
        check_updates.shutil.which = lambda name: None if name == "flatpak" else "/usr/bin/" + name

    def _restore(self):
        check_updates.shutil.which = self._real_which
        for name, value in self.patches.items():
            setattr(check_updates, name, value)

    def test_reports_mise_row_and_total(self):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            check_updates.main()
        result = json.loads(buf.getvalue())
        mise = [r for r in result["repos"] if r["id"] == "mise"]
        self.assertEqual(len(mise), 1)
        self.assertEqual(mise[0]["count"], 2)
        self.assertEqual(mise[0]["pkgCount"], 8)
        self.assertTrue(mise[0]["installed"])
        self.assertIn("mise up", mise[0]["updateCmd"])
        self.assertEqual(result["total"], 5)
        self.assertEqual(self.saved["mise"], 8)

    def test_mise_row_hidden_when_not_installed(self):
        import io
        from contextlib import redirect_stdout

        check_updates.mise_binary = lambda: None
        buf = io.StringIO()
        with redirect_stdout(buf):
            check_updates.main()
        result = json.loads(buf.getvalue())
        mise = [r for r in result["repos"] if r["id"] == "mise"][0]
        self.assertFalse(mise["installed"])
        self.assertEqual(result["total"], 3)


if __name__ == "__main__":
    unittest.main()
