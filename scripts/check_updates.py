#!/usr/bin/env python3
"""Check Arch, AUR, Flatpak, and Omarchy for available updates."""

from __future__ import annotations

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any


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

    # Repo checks hit the network and are independent; run them concurrently so
    # total scan time is the slowest single check instead of the sum of all.
    with ThreadPoolExecutor(max_workers=7) as pool:
        f_pacman = pool.submit(check_pacman)
        f_aur = pool.submit(check_aur, helper)
        f_flatpak = pool.submit(check_flatpak) if flatpak_installed else None
        f_omarchy = pool.submit(check_omarchy)
        f_installed = pool.submit(installed_pkg_names)
        f_flatpak_pkgs = pool.submit(flatpak_pkg_count) if flatpak_installed else None
        f_omarchy_pkgs = pool.submit(lambda: omarchy_pkg_count(f_installed.result()))

    pacman_count = f_pacman.result()
    aur_count = f_aur.result()
    flatpak_count = f_flatpak.result() if f_flatpak else 0
    omarchy_count = f_omarchy.result()

    installed = f_installed.result()
    pacman_pkgs = len(installed)
    aur_pkgs = aur_pkg_count() if helper is not None else 0
    flatpak_pkgs = f_flatpak_pkgs.result() if f_flatpak_pkgs else 0
    omarchy_pkgs = f_omarchy_pkgs.result()

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
    ]

    total = pacman_count + aur_count + flatpak_count + omarchy_count

    result = {
        "repos": repos,
        "total": total,
    }

    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
