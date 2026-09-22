#!/usr/bin/env python3
"""Check Arch, AUR, Flatpak, Omarchy, and mise for available updates."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# Inventory counts ("N pkgs" captions) change only when packages are
# installed/removed, so they ride a 24h disk cache instead of being
# re-queried on every poll. Update counts stay live every run.
PKG_COUNTS_TTL_S = 24 * 3600


def pkg_counts_cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return Path(base) / "omarchy" / "dizziee.system-updates-pkgcounts.json"


def load_pkg_counts() -> dict[str, int] | None:
    try:
        path = pkg_counts_cache_path()
        if not path.is_file():
            return None
        if time.time() - path.stat().st_mtime > PKG_COUNTS_TTL_S:
            return None
        counts = json.loads(path.read_text()).get("counts")
        if not isinstance(counts, dict):
            return None
        return {str(k): int(v) for k, v in counts.items()}
    except Exception:
        return None


def save_pkg_counts(counts: dict[str, int]) -> None:
    try:
        path = pkg_counts_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"counts": counts}))
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


def check_pacman() -> int:
    if shutil.which("checkupdates") is None:
        return 0
    return count_lines(["checkupdates"])


def check_aur(helper: str | None) -> int:
    if helper is None:
        return 0
    if helper == "checkupdates-aur":
        return count_lines([helper])
    return count_lines([helper, "-Qua"])


def check_flatpak() -> int:
    if shutil.which("flatpak") is None:
        return 0
    return count_lines(["flatpak", "remote-ls", "--updates"])


def check_omarchy() -> int:
    if shutil.which("omarchy-update-available") is None:
        return 0
    try:
        result = subprocess.run(
            ["omarchy-update-available"], capture_output=True, text=True, timeout=30
        )
        return 1 if result.returncode == 0 else 0
    except Exception:
        return 0


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


def check_mise(binary: str | None) -> int:
    if binary is None:
        return 0
    # Mirror what `omarchy update` installs: omarchy-update-mise runs
    # `MISE_MINIMUM_RELEASE_AGE=0 mise up`, so drop mise's release cooldown to
    # count the versions that command would actually pull in. Fall back to the
    # plain query on mise builds that reject the override.
    outdated = run_mise_outdated(binary, "0")
    if outdated is None:
        outdated = run_mise_outdated(binary, None)
    return len(outdated) if outdated is not None else 0


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


def collect_repo(id: str, name: str, count: int, pkg_count: int, icon: str, update_cmd: str, installed: bool) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "count": count,
        "pkgCount": pkg_count,
        "icon": icon,
        "updateCmd": update_cmd,
        "installed": installed,
    }


def main() -> int:
    helper = aur_helper()
    flatpak_installed = shutil.which("flatpak") is not None
    mise = mise_binary()

    cached_counts = load_pkg_counts()
    # A cache written before the mise source existed lacks its key; recompute
    # the whole inventory once rather than reporting 0 mise tools for a day.
    if cached_counts is not None and "mise" not in cached_counts:
        cached_counts = None

    # Repo checks hit the network and are independent; run them concurrently so
    # total scan time is the slowest single check instead of the sum of all.
    with ThreadPoolExecutor(max_workers=5) as pool:
        f_pacman = pool.submit(check_pacman)
        f_aur = pool.submit(check_aur, helper)
        f_flatpak = pool.submit(check_flatpak) if flatpak_installed else None
        f_omarchy = pool.submit(check_omarchy)
        f_mise = pool.submit(check_mise, mise) if mise is not None else None

    pacman_count = f_pacman.result()
    aur_count = f_aur.result()
    flatpak_count = f_flatpak.result() if f_flatpak else 0
    omarchy_count = f_omarchy.result()
    mise_count = f_mise.result() if f_mise else 0

    if cached_counts is not None:
        pacman_pkgs = cached_counts.get("pacman", 0)
        aur_pkgs = cached_counts.get("aur", 0) if helper is not None else 0
        flatpak_pkgs = cached_counts.get("flatpak", 0) if flatpak_installed else 0
        omarchy_pkgs = cached_counts.get("omarchy", 0)
        mise_pkgs = cached_counts.get("mise", 0) if mise is not None else 0
    else:
        installed = installed_pkg_names()
        pacman_pkgs = len(installed)
        aur_pkgs = aur_pkg_count() if helper is not None else 0
        flatpak_pkgs = flatpak_pkg_count() if flatpak_installed else 0
        omarchy_pkgs = omarchy_pkg_count(installed)
        mise_pkgs = mise_tool_count(mise) if mise is not None else 0
        save_pkg_counts({
            "pacman": pacman_pkgs,
            "aur": aur_pkgs,
            "flatpak": flatpak_pkgs,
            "omarchy": omarchy_pkgs,
            "mise": mise_pkgs,
        })

    repos = [
        collect_repo("pacman", "Arch", pacman_count, pacman_pkgs, "arch-logo.svg",
            "sudo env OMARCHY_ALLOW_DIRECT_PACMAN=1 pacman -Syu; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
            True),
        collect_repo("aur", "AUR", aur_count, aur_pkgs, "arch-logo.svg",
            aur_update_cmd(helper),
            helper is not None),
        collect_repo("flatpak", "Flatpak", flatpak_count, flatpak_pkgs, "flatpak.svg",
            "flatpak update; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
            flatpak_installed),
        collect_repo("omarchy", "Omarchy", omarchy_count, omarchy_pkgs, "omarchy.svg",
            "omarchy update; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
            True),
        collect_repo("mise", "mise", mise_count, mise_pkgs, "mise.svg",
            "MISE_MINIMUM_RELEASE_AGE=0 mise up; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
            mise is not None),
    ]

    total = pacman_count + aur_count + flatpak_count + omarchy_count + mise_count

    result = {
        "repos": repos,
        "total": total,
    }

    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
