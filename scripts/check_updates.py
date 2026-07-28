#!/usr/bin/env python3
"""Check Arch, AUR, and Flatpak for available updates."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


def count_lines(command: list[str]) -> int:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
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


def pacman_pkg_count() -> int:
    return count_lines(["pacman", "-Qq"])


def aur_pkg_count() -> int:
    return count_lines(["pacman", "-Qqm"])


def flatpak_pkg_count() -> int:
    return count_lines(["flatpak", "list", "--columns=app"])


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
    pacman_count = check_pacman()
    aur_count = check_aur(helper)
    flatpak_installed = shutil.which("flatpak") is not None
    flatpak_count = check_flatpak() if flatpak_installed else 0

    pacman_pkgs = pacman_pkg_count()
    aur_pkgs = aur_pkg_count() if helper is not None else 0
    flatpak_pkgs = flatpak_pkg_count() if flatpak_installed else 0

    repos = [
        collect_repo("pacman", "Arch", pacman_count, pacman_pkgs, "arch-logo.svg",
            "sudo pacman -Syu; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
            True),
        collect_repo("aur", "AUR", aur_count, aur_pkgs, "arch-logo.svg",
            aur_update_cmd(helper),
            helper is not None),
        collect_repo("flatpak", "Flatpak", flatpak_count, flatpak_pkgs, "flatpak.svg",
            "flatpak update; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
            flatpak_installed),
    ]

    total = pacman_count + aur_count + flatpak_count

    result = {
        "repos": repos,
        "total": total,
        "ready": True,
    }

    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
