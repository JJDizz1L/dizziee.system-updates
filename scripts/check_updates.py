#!/usr/bin/env python3
"""Check Arch, AUR, Flatpak, AppImage, and Omarchy for available updates."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# De-facto AppImage locations (relative to $HOME): ~/Applications is the
# default integration target of AppImageLauncher (its own config default) and
# Gear Lever; ~/.local/share/AppImage is AppImagePool's download directory;
# ~/.local/bin is the classic manual drop spot (appimaged watched it);
# ~/AppImages is a common manual convention. Deliberately excluded:
# ~/Downloads (a staging area the integration tools move apps OUT of, so it
# would make counts noisy) and /opt (system-wide, not user-writable).
# The shell-side update command is built from the same list, so checker and
# updater never disagree.
APPIMAGE_SCAN_DIRS = ("Applications", "AppImages", ".local/share/AppImage", ".local/bin")


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


def appimage_files() -> list[Path]:
    home = Path.home()
    files: set[Path] = set()
    for rel in APPIMAGE_SCAN_DIRS:
        directory = home / rel
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if entry.is_file() and entry.suffix.lower() == ".appimage":
                # Resolve so a *.AppImage symlinked into a second scan dir
                # (e.g. ~/.local/bin) counts once, not twice.
                files.add(entry.resolve())
    return sorted(files)


def check_appimage(appimages: list[Path]) -> tuple[int, int]:
    # appimageupdatetool --check-for-update: exit 1 = update available,
    # 0 = up to date, 2 = error (includes AppImages without update info).
    # The tool can also DIE BY SIGNAL (its GitHub API check throws uncaught on
    # e.g. rate limiting), so any exit other than 0/1 means "unknown" — never
    # let a failed check masquerade as "up to date".
    def probe(path: Path) -> int:
        try:
            result = subprocess.run(
                ["appimageupdatetool", "--check-for-update", str(path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return result.returncode
        except Exception:
            return -1

    # One network round trip per AppImage; check them concurrently.
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(probe, appimages))
    updates = sum(1 for rc in codes if rc == 1)
    unchecked = sum(1 for rc in codes if rc not in (0, 1))
    return updates, unchecked


def appimage_setup_cmd() -> str:
    script = Path(__file__).resolve().parent / "install_appimageupdatetool.sh"
    # Quoted: a $HOME with spaces must not break the install command.
    return f"bash {shlex.quote(str(script))}; echo; read -n 1 -s -r -p 'Done. Press any key to close'"


def appimage_update_cmd() -> str:
    globs = " ".join(f"~/{rel}/*.AppImage" for rel in APPIMAGE_SCAN_DIRS)
    # readlink -f + seen-map: a *.AppImage symlinked into a second scan dir is
    # updated once, via its REAL path — overwriting through the symlink would
    # replace the link with a regular file and leave the original stale.
    return (
        "shopt -s nullglob nocaseglob; declare -A seen; "
        f"for f in {globs}; do "
        'r=$(readlink -f "$f"); '
        '[[ -n ${seen[$r]:-} ]] && continue; seen[$r]=1; '
        'echo "== $r"; '
        'appimageupdatetool --overwrite --remove-old "$r" || echo "not updated (see above): $r"; '
        "done; echo; read -n 1 -s -r -p 'Done. Press any key to close'"
    )


def aur_update_cmd(helper: str | None) -> str:
    if helper is None:
        return ""
    if helper == "checkupdates-aur":
        return f"{helper}; echo; read -n 1 -s -r -p 'Done. Press any key to close'"
    return f"{helper} -Sua; echo; read -n 1 -s -r -p 'Done. Press any key to close'"


def appimage_repo(count: int, unchecked: int, pkg_count: int, tool_installed: bool, visible: bool) -> dict[str, Any]:
    repo = collect_repo("appimage", "AppImage", count, pkg_count, "appimage.svg",
        appimage_update_cmd(),
        visible)
    repo["needsTool"] = not tool_installed
    repo["setupCmd"] = appimage_setup_cmd()
    if unchecked > 0:
        repo["unchecked"] = unchecked
    return repo


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
    appimage_installed = shutil.which("appimageupdatetool") is not None
    # Local filesystem scan; cheap enough to stay synchronous.
    appimages = appimage_files()

    # Repo checks hit the network and are independent; run them concurrently so
    # total scan time is the slowest single check instead of the sum of all.
    with ThreadPoolExecutor(max_workers=7) as pool:
        f_pacman = pool.submit(check_pacman)
        f_aur = pool.submit(check_aur, helper)
        f_flatpak = pool.submit(check_flatpak) if flatpak_installed else None
        f_appimage = pool.submit(check_appimage, appimages) if appimage_installed and appimages else None
        f_omarchy = pool.submit(check_omarchy)
        f_installed = pool.submit(installed_pkg_names)
        f_flatpak_pkgs = pool.submit(flatpak_pkg_count) if flatpak_installed else None
        f_omarchy_pkgs = pool.submit(lambda: omarchy_pkg_count(f_installed.result()))

    pacman_count = f_pacman.result()
    aur_count = f_aur.result()
    flatpak_count = f_flatpak.result() if f_flatpak else 0
    appimage_count, appimage_unchecked = f_appimage.result() if f_appimage else (0, 0)
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
        # AppImages present means the row shows even without the tool: the
        # Install-tool button is how users discover the dependency.
        appimage_repo(
            appimage_count,
            appimage_unchecked,
            len(appimages),
            tool_installed=appimage_installed,
            visible=len(appimages) > 0,
        ),
        collect_repo("omarchy", "Omarchy", omarchy_count, omarchy_pkgs, "omarchy.svg",
            "omarchy update; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
            True),
    ]

    total = pacman_count + aur_count + flatpak_count + appimage_count + omarchy_count

    result = {
        "repos": repos,
        "total": total,
    }

    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
