"""Tests for scripts/check_updates.py.

Run with: python3 -m unittest discover -s tests
"""

import importlib.util
import json
import subprocess
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


def pkg(name, frm="", to=""):
    return {"name": name, "from": frm, "to": to}


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

    def test_no_binary_is_empty(self):
        self.assertEqual(check_updates.check_mise(None), [])
        self.assertEqual(self.calls, [])

    def test_lists_outdated_tools(self):
        self.responses.append({"codex": {"current": "1.0", "latest": "1.1"},
                               "claude": {"current": "2.0", "latest": "3.0"}})
        result = check_updates.check_mise("/usr/bin/mise")
        self.assertEqual([p["name"] for p in result], ["codex", "claude"])
        self.assertEqual(result[0], pkg("codex", "1.0", "1.1"))
        self.assertEqual(self.calls, ["0"])

    def test_strips_version_suffix_from_key(self):
        self.responses.append({"node@20": {"current": "20.0", "requested": "21.0"}})
        self.assertEqual(check_updates.check_mise("/usr/bin/mise"), [pkg("node", "20.0", "21.0")])

    def test_falls_back_without_override_when_rejected(self):
        self.responses.extend([None, {"codex": {"current": "1", "latest": "2"}}])
        self.assertEqual(len(check_updates.check_mise("/usr/bin/mise")), 1)
        self.assertEqual(self.calls, ["0", None])

    def test_empty_when_everything_current(self):
        self.responses.append({})
        self.assertEqual(check_updates.check_mise("/usr/bin/mise"), [])

    def test_empty_when_both_probes_fail(self):
        self.responses.extend([None, None])
        self.assertEqual(check_updates.check_mise("/usr/bin/mise"), [])


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


class MiseToolUrlsTests(unittest.TestCase):
    def setUp(self):
        self._real = check_updates.command_lines
        self.addCleanup(lambda: setattr(check_updates, "command_lines", self._real))

    def test_maps_aqua_and_github_backends(self):
        check_updates.command_lines = lambda *a, **k: [
            "claude  aqua:anthropics/claude-code http:claude",
            "node    core:node",
            "7z      aqua:ip7z/7zip github:ip7z/7zip",
        ]
        urls = check_updates.mise_tool_urls("/usr/bin/mise")
        self.assertEqual(urls["claude"], "https://github.com/anthropics/claude-code")
        self.assertEqual(urls["7z"], "https://github.com/ip7z/7zip")
        self.assertNotIn("node", urls)

    def test_skips_reverse_dns_aqua_ids(self):
        check_updates.command_lines = lambda *a, **k: [
            "acli  aqua:atlassian.com/acli",
            "claude  aqua:anthropics/claude-code",
        ]
        urls = check_updates.mise_tool_urls("/usr/bin/mise")
        self.assertNotIn("acli", urls)
        self.assertEqual(urls["claude"], "https://github.com/anthropics/claude-code")

    def test_no_binary_is_empty(self):
        self.assertEqual(check_updates.mise_tool_urls(None), {})


class ParseVersionLinesTests(unittest.TestCase):
    def test_parses_arrow_lines(self):
        lines = ["linux 6.10.1 -> 6.10.2", "mesa 24.1.0-1 -> 24.1.1-1"]
        self.assertEqual(
            check_updates.parse_version_lines(lines),
            [pkg("linux", "6.10.1", "6.10.2"), pkg("mesa", "24.1.0-1", "24.1.1-1")],
        )

    def test_skips_blank_lines(self):
        self.assertEqual(check_updates.parse_version_lines(["", "  "]), [])

    def test_falls_back_to_first_two_tokens(self):
        self.assertEqual(
            check_updates.parse_version_lines(["weird 1.2 extra words"]),
            [pkg("weird", "", "1.2")],
        )


class CheckPackageListTests(unittest.TestCase):
    def setUp(self):
        self._real_cmd = check_updates.command_lines
        self._real_which = check_updates.shutil.which
        check_updates.command_lines = lambda *a, **k: ["foo 1.0 -> 2.0", "bar 3.0 -> 4.0"]
        self.addCleanup(lambda: setattr(check_updates, "command_lines", self._real_cmd))
        self.addCleanup(lambda: setattr(check_updates.shutil, "which", self._real_which))

    def test_pacman_returns_packages(self):
        check_updates.shutil.which = lambda name: "/usr/bin/" + name
        self.assertEqual(
            check_updates.check_pacman(),
            [pkg("foo", "1.0", "2.0"), pkg("bar", "3.0", "4.0")],
        )

    def test_missing_checkupdates_is_empty(self):
        check_updates.shutil.which = lambda name: None
        self.assertEqual(check_updates.check_pacman(), [])


class ResolveLinkTests(unittest.TestCase):
    def test_github_gets_releases(self):
        link = check_updates.resolve_link("https://github.com/owner/repo")
        self.assertEqual(link["url"], "https://github.com/owner/repo/releases")
        self.assertEqual(link["label"], "Release notes")

    def test_github_normalizes_suffixes(self):
        link = check_updates.resolve_link("https://github.com/owner/repo.git/")
        self.assertEqual(link["url"], "https://github.com/owner/repo/releases")

    def test_gitlab_com_gets_releases(self):
        link = check_updates.resolve_link("https://gitlab.com/owner/repo")
        self.assertEqual(link["url"], "https://gitlab.com/owner/repo/-/releases")
        self.assertEqual(link["label"], "Release notes")

    def test_gitlab_instance_gets_releases(self):
        link = check_updates.resolve_link("https://gitlab.gnome.org/GNOME/foo")
        self.assertEqual(link["url"], "https://gitlab.gnome.org/GNOME/foo/-/releases")

    def test_gitlab_tree_url_is_trimmed(self):
        link = check_updates.resolve_link("https://gitlab.gnome.org/GNOME/foo/tree/main")
        self.assertEqual(link["url"], "https://gitlab.gnome.org/GNOME/foo/-/releases")

    def test_codeberg_gets_releases(self):
        link = check_updates.resolve_link("https://codeberg.org/owner/repo")
        self.assertEqual(link["url"], "https://codeberg.org/owner/repo/releases")

    def test_plain_upstream_is_repo(self):
        link = check_updates.resolve_link("https://example.org/thing")
        self.assertEqual(link["url"], "https://example.org/thing")
        self.assertEqual(link["label"], "Repo")

    def test_missing_upstream_uses_fallback(self):
        link = check_updates.resolve_link(None, "https://flathub.org/apps/org.foo.Bar")
        self.assertEqual(link["url"], "https://flathub.org/apps/org.foo.Bar")
        self.assertEqual(link["label"], "Repo")


class WithLinksTests(unittest.TestCase):
    def test_attaches_url_and_label(self):
        result = check_updates.with_links(
            [pkg("foo", "1", "2")],
            {"foo": "https://github.com/owner/repo"},
            lambda name: "https://fallback/" + name,
        )
        self.assertEqual(result[0]["url"], "https://github.com/owner/repo/releases")
        self.assertEqual(result[0]["label"], "Release notes")

    def test_uses_fallback_without_upstream(self):
        result = check_updates.with_links(
            [pkg("foo")], {}, lambda name: "https://fallback/" + name
        )
        self.assertEqual(result[0]["url"], "https://fallback/foo")


class NormalizeRemoteTests(unittest.TestCase):
    def test_scp_style_ssh_remote(self):
        self.assertEqual(
            check_updates.normalize_remote("git@github.com:dbachelder/omarchy-istats.git"),
            "https://github.com/dbachelder/omarchy-istats",
        )

    def test_ssh_url_remote(self):
        self.assertEqual(
            check_updates.normalize_remote("ssh://git@github.com/owner/repo.git"),
            "https://github.com/owner/repo",
        )

    def test_https_passthrough(self):
        self.assertEqual(
            check_updates.normalize_remote("https://github.com/owner/repo.git"),
            "https://github.com/owner/repo.git",
        )

    def test_other_scheme_passthrough(self):
        self.assertEqual(
            check_updates.normalize_remote("git://example.org/repo"),
            "git://example.org/repo",
        )

    def test_empty(self):
        self.assertEqual(check_updates.normalize_remote(None), "")


class PluginUpdateTests(unittest.TestCase):
    def setUp(self):
        self._real = check_updates._run_git
        self.responses = {}
        check_updates._run_git = self._fake
        self.addCleanup(lambda: setattr(check_updates, "_run_git", self._real))

    def _fake(self, args, cwd, timeout=None):
        key = " ".join(args)
        if key in self.responses:
            return self.responses[key]
        if args[0] == "fetch":
            return completed()
        return completed(returncode=1)

    def test_reports_plugin_behind_origin(self):
        self.responses["rev-parse HEAD"] = completed(stdout="aaaaaaa1111")
        self.responses["rev-parse FETCH_HEAD"] = completed(stdout="bbbbbbb2222")
        self.responses["rev-list --count HEAD..FETCH_HEAD"] = completed(stdout="3")
        self.responses["remote get-url origin"] = completed(
            stdout="git@github.com:owner/repo.git"
        )
        entry = check_updates.plugin_update(Path("/plugins/cool-plugin"))
        self.assertEqual(entry["name"], "cool-plugin")
        self.assertEqual(entry["from"], "aaaaaaa")
        self.assertEqual(entry["to"], "3 new commits")
        self.assertEqual(entry["upstream"], "git@github.com:owner/repo.git")

    def test_single_commit_label_is_singular(self):
        self.responses["rev-parse HEAD"] = completed(stdout="aaaaaaa1111")
        self.responses["rev-parse FETCH_HEAD"] = completed(stdout="bbbbbbb2222")
        self.responses["rev-list --count HEAD..FETCH_HEAD"] = completed(stdout="1")
        self.assertEqual(check_updates.plugin_update(Path("/plugins/p"))["to"], "1 new commit")

    def test_up_to_date_is_none(self):
        self.responses["rev-parse HEAD"] = completed(stdout="same")
        self.responses["rev-parse FETCH_HEAD"] = completed(stdout="same")
        self.assertIsNone(check_updates.plugin_update(Path("/plugins/p")))

    def test_fetch_failure_is_none(self):
        self.responses["fetch --quiet origin HEAD"] = completed(returncode=1)
        self.assertIsNone(check_updates.plugin_update(Path("/plugins/p")))

    def test_check_plugins_skips_current(self):
        def fake(dir_path):
            return None if dir_path.name == "current" else {"name": dir_path.name}

        self._real = check_updates.plugin_update
        check_updates.plugin_update = fake
        self.addCleanup(lambda: setattr(check_updates, "plugin_update", self._real))
        result = check_updates.check_plugins([Path("/plugins/behind"), Path("/plugins/current")])
        self.assertEqual([p["name"] for p in result], ["behind"])

    def test_check_plugins_empty(self):
        self.assertEqual(check_updates.check_plugins([]), [])


class MainIntegrationTests(unittest.TestCase):
    """main() must surface per-repo package detail and include mise in the total."""

    def setUp(self):
        self.saved = {}
        self.patches = {}
        for name, value in {
            "aur_helper": lambda: None,
            "check_pacman": lambda: [pkg("linux", "1", "2"), pkg("mesa", "1", "2"), pkg("glibc", "1", "2")],
            "check_omarchy": lambda: [],
            "check_mise": lambda binary: [pkg("claude", "1", "2"), pkg("codex", "1", "2")],
            "mise_binary": lambda: "/usr/bin/mise",
            "mise_tool_count": lambda binary: 8,
            "mise_tool_urls": lambda binary: {"claude": "https://github.com/anthropics/claude-code"},
            "installed_pkg_names": lambda: set(),
            "installed_upstream_urls": lambda: {"linux": "https://github.com/torvalds/linux"},
            "omarchy_pkg_count": lambda installed: 0,
            "git_plugin_dirs": lambda: [Path("/plugins/one"), Path("/plugins/two")],
            "check_plugins": lambda dirs: [
                {"name": "one", "from": "abc1234", "to": "2 new commits",
                 "upstream": "git@github.com:owner/one.git"}
            ],
            "load_cache": lambda: None,
            "save_cache": lambda counts, urls: self.saved.update(counts),
        }.items():
            self.patches[name] = getattr(check_updates, name)
            setattr(check_updates, name, value)
        self.addCleanup(self._restore)
        self._real_which = check_updates.shutil.which
        check_updates.shutil.which = lambda name: None if name == "flatpak" else "/usr/bin/" + name

    def _restore(self):
        check_updates.shutil.which = self._real_which
        for name, value in self.patches.items():
            setattr(check_updates, name, value)

    def _run(self):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            check_updates.main()
        return json.loads(buf.getvalue())

    def test_reports_mise_row_and_total(self):
        result = self._run()
        mise = [r for r in result["repos"] if r["id"] == "mise"]
        self.assertEqual(len(mise), 1)
        self.assertEqual(mise[0]["count"], 2)
        self.assertEqual(mise[0]["pkgCount"], 8)
        self.assertTrue(mise[0]["installed"])
        self.assertIn("mise up", mise[0]["updateCmd"])
        self.assertEqual(result["total"], 6)
        self.assertEqual(self.saved["mise"], 8)

    def test_reports_plugins_row(self):
        result = self._run()
        plugins = [r for r in result["repos"] if r["id"] == "plugins"][0]
        self.assertTrue(plugins["installed"])
        self.assertEqual(plugins["count"], 1)
        self.assertEqual(plugins["pkgCount"], 2)
        self.assertIn("omarchy plugin update", plugins["updateCmd"])
        package = plugins["packages"][0]
        # The plugin's own SSH remote becomes an https release-notes link.
        self.assertEqual(package["url"], "https://github.com/owner/one/releases")
        self.assertEqual(package["label"], "Release notes")

    def test_emits_packages_with_links(self):
        result = self._run()
        pacman = [r for r in result["repos"] if r["id"] == "pacman"][0]
        self.assertEqual(len(pacman["packages"]), 3)
        linux = [p for p in pacman["packages"] if p["name"] == "linux"][0]
        self.assertEqual(linux["url"], "https://github.com/torvalds/linux/releases")
        self.assertEqual(linux["label"], "Release notes")
        # A package with no upstream URL still gets a fallback link.
        mesa = [p for p in pacman["packages"] if p["name"] == "mesa"][0]
        self.assertEqual(mesa["url"], "https://archlinux.org/packages/?q=mesa")

        mise = [r for r in result["repos"] if r["id"] == "mise"][0]
        claude = [p for p in mise["packages"] if p["name"] == "claude"][0]
        self.assertEqual(claude["url"], "https://github.com/anthropics/claude-code/releases")

    def test_mise_row_hidden_when_not_installed(self):
        check_updates.mise_binary = lambda: None
        result = self._run()
        mise = [r for r in result["repos"] if r["id"] == "mise"][0]
        self.assertFalse(mise["installed"])
        self.assertEqual(result["total"], 4)

    def test_plugins_row_hidden_when_none_installed(self):
        check_updates.git_plugin_dirs = lambda: []
        result = self._run()
        plugins = [r for r in result["repos"] if r["id"] == "plugins"][0]
        self.assertFalse(plugins["installed"])
        self.assertEqual(plugins["count"], 0)
        self.assertEqual(result["total"], 5)


if __name__ == "__main__":
    unittest.main()
