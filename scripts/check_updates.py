#!/usr/bin/env python3
"""Check Arch, AUR, Flatpak, Omarchy, and mise for available updates."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

# Inventory counts ("N pkgs" captions) and package upstream URLs change only
# when packages are installed/removed, so they ride a 24h disk cache instead
# of being re-queried on every poll. Update counts stay live every run.
PKG_COUNTS_TTL_S = 24 * 3600

# The Omarchy row has no per-package metadata of its own; both the packaged
# build and a dev checkout upstream to the same repository.
OMARCHY_REPO = "https://github.com/basecamp/omarchy"
MISE_REGISTRY_URL = "https://mise.jdx.dev/registry.html"

# `checkupdates`, `pacman -Qu`, and `yay/paru -Qua` all print
# "name oldver -> newver".
VERSION_LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+->\s+(\S+)$")
GITHUB_RE = re.compile(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)", re.I)
GITLAB_HOST_RE = re.compile(r"^https?://(?:www\.)?(gitlab[^/]*)\.([^/]+)/", re.I)
CODEBERG_RE = re.compile(r"^https?://(?:www\.)?codeberg\.org/([^/]+)/([^/#?]+)", re.I)
# mise registry backends that name a GitHub repository directly.
MISE_GITHUB_BACKEND_RE = re.compile(r"^(?:aqua|github):([^/\s]+)/([^/\s]+)$")


def pkg_counts_cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return Path(base) / "omarchy" / "dizziee.system-updates-pkgcounts.json"


def load_cache() -> dict[str, Any] | None:
    """Return {"counts": {...}, "urls": {...}} from the 24h cache, or None."""
    try:
        path = pkg_counts_cache_path()
        if not path.is_file():
            return None
        if time.time() - path.stat().st_mtime > PKG_COUNTS_TTL_S:
            return None
        data = json.loads(path.read_text())
        counts = data.get("counts")
        urls = data.get("urls")
        if not isinstance(counts, dict) or not isinstance(urls, dict):
            return None
        return {
            "counts": {str(k): int(v) for k, v in counts.items()},
            "urls": {str(k): str(v) for k, v in urls.items()},
        }
    except Exception:
        return None


def save_cache(counts: dict[str, int], urls: dict[str, str]) -> None:
    try:
        path = pkg_counts_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"counts": counts, "urls": urls}))
    except Exception:
        pass


def count_lines(command: list[str], timeout: int = 30) -> int:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return 0
        return len([line for line in result.stdout.strip().split("\n") if line.strip()])
    except Exception:
        return 0


def command_lines(command: list[str], timeout: int = 30, require_ok: bool = True) -> list[str]:
    """Run a command and return its non-empty stdout lines.

    require_ok=False keeps stdout on a nonzero exit: checkupdates exits 2 with
    no output when everything is current, and some helpers are noisy on exit.
    """
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if require_ok and result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def parse_version_lines(lines: list[str]) -> list[dict[str, str]]:
    """Parse "name oldver -> newver" lines into package entries."""
    packages = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        match = VERSION_LINE_RE.match(line)
        if match:
            packages.append({"name": match.group(1), "from": match.group(2), "to": match.group(3)})
            continue
        parts = line.split()
        packages.append(
            {"name": parts[0], "from": "", "to": parts[1] if len(parts) > 1 else ""}
        )
    return packages


def installed_upstream_urls() -> dict[str, str]:
    """Map installed package name -> upstream URL from local package metadata."""
    if shutil.which("expac"):
        urls: dict[str, str] = {}
        for line in command_lines(["expac", "-Q", "%n|%u"]):
            name, _, url = line.partition("|")
            if name.strip() and url.strip():
                urls[name.strip()] = url.strip()
        return urls
    # Fallback when expac is missing: one bulk `pacman -Qi` parse.
    try:
        result = subprocess.run(["pacman", "-Qi"], capture_output=True, text=True, timeout=60)
    except Exception:
        return {}
    urls = {}
    name = None
    for line in result.stdout.splitlines():
        if line.startswith("Name "):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("URL ") and name:
            urls[name] = line.split(":", 1)[1].strip()
    return urls


def resolve_link(
    upstream: str | None, fallback_url: str = "", fallback_label: str = "Repo"
) -> dict[str, str]:
    """Pick a package link: release notes on known code hosts, else the repo.

    Heuristic and offline — no per-package network probe. GitHub, GitLab, and
    Codeberg upstreams get their releases page; anything else links to the
    upstream URL itself, and a missing upstream falls back to the registry page.
    """
    url = (upstream or "").strip()
    if url:
        match = GITHUB_RE.match(url)
        if match:
            repo = re.sub(r"\.git$", "", match.group(2))
            return {
                "url": f"https://github.com/{match.group(1)}/{repo}/releases",
                "label": "Release notes",
            }
        if GITLAB_HOST_RE.match(url):
            base = url.split("/-/")[0].split("/tree/")[0].rstrip("/")
            return {"url": base + "/-/releases", "label": "Release notes"}
        match = CODEBERG_RE.match(url)
        if match:
            repo = re.sub(r"\.git$", "", match.group(2))
            return {
                "url": f"https://codeberg.org/{match.group(1)}/{repo}/releases",
                "label": "Release notes",
            }
        return {"url": url, "label": "Repo"}
    return {"url": fallback_url, "label": fallback_label}


def with_links(
    packages: list[dict[str, str]],
    upstream_urls: dict[str, str],
    fallback: Callable[[str], str],
) -> list[dict[str, str]]:
    linked = []
    for package in packages:
        link = resolve_link(upstream_urls.get(package["name"]), fallback(package["name"]))
        linked.append({**package, "url": link["url"], "label": link["label"]})
    return linked


def arch_fallback_url(name: str) -> str:
    return f"https://archlinux.org/packages/?q={name}"


def aur_fallback_url(name: str) -> str:
    return f"https://aur.archlinux.org/packages/{name}"


def flatpak_fallback_url(name: str) -> str:
    return f"https://flathub.org/apps/{name}"


def aur_helper() -> str | None:
    for helper in ("checkupdates-aur",):
        if shutil.which(helper):
            return helper
    for helper in ("yay", "paru"):
        if shutil.which(helper):
            return helper
    return None


def installed_pkg_names() -> set[str]:
    try:
        result = subprocess.run(["pacman", "-Qq"], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return set()
        return set(result.stdout.split())
    except Exception:
        return set()


def aur_pkg_count() -> int:
    return count_lines(["pacman", "-Qqm"])


def flatpak_pkg_count() -> int:
    return count_lines(["flatpak", "list", "--columns=app"])


def omarchy_pkg_count(installed: set[str]) -> int:
    try:
        result = subprocess.run(["pacman", "-Slq", "omarchy"], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return 0
        return len(set(result.stdout.split()).intersection(installed))
    except Exception:
        return 0


def check_pacman() -> list[dict[str, str]]:
    if shutil.which("checkupdates") is None:
        return []
    # checkupdates exits 2 (with no output) when everything is current.
    return parse_version_lines(command_lines(["checkupdates"], require_ok=False))


def check_aur(helper: str | None) -> list[dict[str, str]]:
    if helper is None:
        return []
    if helper == "checkupdates-aur":
        return parse_version_lines(command_lines([helper], require_ok=False))
    return parse_version_lines(command_lines([helper, "-Qua"], require_ok=False))


def check_flatpak() -> list[dict[str, str]]:
    if shutil.which("flatpak") is None:
        return []
    lines = command_lines(
        ["flatpak", "remote-ls", "--updates", "--columns=application,version"],
        require_ok=False,
    )
    packages = []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        packages.append({"name": parts[0], "from": "", "to": parts[-1] if len(parts) > 1 else ""})
    return packages


def check_omarchy() -> list[dict[str, str]]:
    if shutil.which("omarchy-update-available") is None:
        return []
    try:
        result = subprocess.run(
            ["omarchy-update-available"], capture_output=True, text=True, timeout=30
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    packages = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        match = VERSION_LINE_RE.match(line)
        if match:
            packages.append(
                {"name": match.group(1), "from": match.group(2), "to": match.group(3)}
            )
        else:
            parts = line.split()
            packages.append({"name": parts[0], "from": "", "to": " ".join(parts[1:])})
    return packages


def mise_binary() -> str | None:
    return shutil.which("mise")


def run_mise_outdated(binary: str, release_age: str | None) -> dict[str, Any] | None:
    """Run `mise outdated --json` and return the parsed object, or None on failure.

    mise resolves the current directory's config, so pin cwd to the user's home
    to read the global config instead of an incidental project directory.
    """
    env = os.environ.copy()
    if release_age is not None:
        env["MISE_MINIMUM_RELEASE_AGE"] = release_age
    try:
        result = subprocess.run(
            [binary, "outdated", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.path.expanduser("~"),
            env=env,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    # Some mise builds reject MISE_MINIMUM_RELEASE_AGE=0 ("Invalid date or
    # duration: 0") but still print "{}" with exit 0, which would read as
    # "everything current". Treat that as a failed probe so the caller can
    # retry without the override.
    if release_age is not None and "invalid date or duration" in result.stderr.lower():
        return None
    return data


def check_mise(binary: str | None) -> list[dict[str, str]]:
    if binary is None:
        return []
    # Mirror what `omarchy update` installs: omarchy-update-mise runs
    # `MISE_MINIMUM_RELEASE_AGE=0 mise up`, so drop mise's release cooldown to
    # count the versions that command would actually pull in. Fall back to the
    # plain query on mise builds that reject the override.
    outdated = run_mise_outdated(binary, "0")
    if outdated is None:
        outdated = run_mise_outdated(binary, None)
    if not outdated:
        return []
    packages = []
    for key, info in outdated.items():
        info = info if isinstance(info, dict) else {}
        current = str(info.get("current") or "")
        latest = str(info.get("latest") or info.get("requested") or "")
        name = str(key).split("@")[0]
        packages.append({"name": name, "from": current, "to": latest})
    return packages


def mise_tool_urls(binary: str | None) -> dict[str, str]:
    """Map mise tool name -> GitHub repo URL using a single `mise registry` call.

    Only backends that name a repository directly (aqua:/github:) resolve; core
    and language-runner backends fall back to the registry page at link time.
    """
    if binary is None:
        return {}
    urls: dict[str, str] = {}
    for line in command_lines([binary, "registry"], require_ok=False):
        parts = line.split()
        if not parts:
            continue
        tool = parts[0]
        for token in parts[1:]:
            match = MISE_GITHUB_BACKEND_RE.match(token)
            # aqua ids are sometimes reverse-DNS (atlassian.com/acli), which is
            # not a GitHub owner/repo; GitHub names never contain dots.
            if match and "." not in match.group(1):
                urls[tool] = f"https://github.com/{match.group(1)}/{match.group(2)}"
                break
    return urls


def mise_tool_count(binary: str | None) -> int:
    if binary is None:
        return 0
    try:
        result = subprocess.run(
            [binary, "ls", "--current", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.path.expanduser("~"),
        )
        if result.returncode != 0:
            return 0
        data = json.loads(result.stdout)
        return len(data) if isinstance(data, dict) else 0
    except Exception:
        return 0


def aur_update_cmd(helper: str | None) -> str:
    if helper is None:
        return ""
    if helper == "checkupdates-aur":
        return f"{helper}; echo; read -n 1 -s -r -p 'Done. Press any key to close'"
    return f"{helper} -Sua; echo; read -n 1 -s -r -p 'Done. Press any key to close'"


def collect_repo(id: str, name: str, packages: list[dict[str, str]], pkg_count: int, icon: str, update_cmd: str, installed: bool) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "count": len(packages),
        "pkgCount": pkg_count,
        "icon": icon,
        "updateCmd": update_cmd,
        "installed": installed,
        "packages": packages,
    }


def mise_fallback_url(name: str) -> str:
    return MISE_REGISTRY_URL


def omarchy_fallback_url(name: str) -> str:
    return OMARCHY_REPO


def main() -> int:
    helper = aur_helper()
    flatpak_installed = shutil.which("flatpak") is not None
    mise = mise_binary()

    cache = load_cache()
    # A cache written before the mise source existed lacks its count key;
    # recompute the whole inventory once rather than reporting 0 mise tools
    # (or an empty URL map) for a day.
    if cache is not None and "mise" not in cache["counts"]:
        cache = None

    # Repo checks hit the network and are independent; run them concurrently so
    # total scan time is the slowest single check instead of the sum of all.
    with ThreadPoolExecutor(max_workers=5) as pool:
        f_pacman = pool.submit(check_pacman)
        f_aur = pool.submit(check_aur, helper)
        f_flatpak = pool.submit(check_flatpak) if flatpak_installed else None
        f_omarchy = pool.submit(check_omarchy)
        f_mise = pool.submit(check_mise, mise) if mise is not None else None

    pacman_updates = f_pacman.result()
    aur_updates = f_aur.result()
    flatpak_updates = f_flatpak.result() if f_flatpak else []
    omarchy_updates = f_omarchy.result()
    mise_updates = f_mise.result() if f_mise else []

    if cache is not None:
        counts = cache["counts"]
        upstream_urls = cache["urls"]
        pacman_pkgs = counts.get("pacman", 0)
        aur_pkgs = counts.get("aur", 0) if helper is not None else 0
        flatpak_pkgs = counts.get("flatpak", 0) if flatpak_installed else 0
        omarchy_pkgs = counts.get("omarchy", 0)
        mise_pkgs = counts.get("mise", 0) if mise is not None else 0
    else:
        installed = installed_pkg_names()
        upstream_urls = installed_upstream_urls()
        pacman_pkgs = len(installed)
        aur_pkgs = aur_pkg_count() if helper is not None else 0
        flatpak_pkgs = flatpak_pkg_count() if flatpak_installed else 0
        omarchy_pkgs = omarchy_pkg_count(installed)
        mise_pkgs = mise_tool_count(mise) if mise is not None else 0
        save_cache(
            {
                "pacman": pacman_pkgs,
                "aur": aur_pkgs,
                "flatpak": flatpak_pkgs,
                "omarchy": omarchy_pkgs,
                "mise": mise_pkgs,
            },
            upstream_urls,
        )

    mise_urls = mise_tool_urls(mise) if mise is not None else {}

    repos = [
        collect_repo("pacman", "Arch",
            with_links(pacman_updates, upstream_urls, arch_fallback_url),
            pacman_pkgs, "arch-logo.svg",
            "sudo env OMARCHY_ALLOW_DIRECT_PACMAN=1 pacman -Syu; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
            True),
        collect_repo("aur", "AUR",
            with_links(aur_updates, upstream_urls, aur_fallback_url),
            aur_pkgs, "arch-logo.svg",
            aur_update_cmd(helper),
            helper is not None),
        collect_repo("flatpak", "Flatpak",
            with_links(flatpak_updates, {}, flatpak_fallback_url),
            flatpak_pkgs, "flatpak.svg",
            "flatpak update; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
            flatpak_installed),
        collect_repo("omarchy", "Omarchy",
            with_links(omarchy_updates, upstream_urls, omarchy_fallback_url),
            omarchy_pkgs, "omarchy.svg",
            "omarchy update; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
            True),
        collect_repo("mise", "mise",
            with_links(mise_updates, mise_urls, mise_fallback_url),
            mise_pkgs, "mise.svg",
            "MISE_MINIMUM_RELEASE_AGE=0 mise up; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
            mise is not None),
    ]

    total = (len(pacman_updates) + len(aur_updates) + len(flatpak_updates)
             + len(omarchy_updates) + len(mise_updates))

    result = {
        "repos": repos,
        "total": total,
    }

    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
