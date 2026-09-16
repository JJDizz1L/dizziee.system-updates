# dizziee.system-updates

System update indicator for the Omarchy bar. Shows available updates from pacman, AUR, Flatpak, AppImage, and Omarchy, with per-repo update buttons.

## Requirements

- `checkupdates` (from `pacman-contrib`)
- AUR helper (`yay`, `paru`, etc.) — optional, AUR detection is automatic
- `flatpak` — optional
- `appimageupdatetool` — optional, enables the AppImage row (see below)

## Installation

```sh
omarchy plugin add https://github.com/JJDizz1L/dizziee.system-updates.git --enable
```

### Then place it in your bar layout with 
`omarchy bar plugin add dizziee.system-updates [--section <left|center|right>]`</br>

Suggested placement: 
```
omarchy bar plugin add dizziee.system-updates --section center
```

You can validate the plugin at any time with:

```sh
omarchy plugin validate ~/.config/omarchy/plugins/dizziee.system-updates
```

## Updating

To pull the latest version of the plugin:

```sh
omarchy plugin update dizziee.system-updates --yes
```

## Configuration
Configuration lives in `~/.config/omarchy/shell.json`.

| Key | Type | Default | Description |
|---|---|---|---|
| `refreshIntervalSec` | integer (300–7200) | 1800 | How often to check for updates (seconds) |
| `alwaysShow` | boolean | true | Keep icon visible even when no updates are available |

## How updates work

The **Arch** update button runs a direct pacman system upgrade:

```sh
sudo env OMARCHY_ALLOW_DIRECT_PACMAN=1 pacman -Syu
```

Omarchy installs a pacman hook (`omarchy-update-pacman-guard`) that aborts a bare `sudo pacman -Syu` to route updates through `omarchy update` — which handles the transcript, snapshot, keyrings, migrations, and post-update hooks. The `OMARCHY_ALLOW_DIRECT_PACMAN=1` env var opts this one transaction past that guard: it upgrades packages directly and skips Omarchy's update pipeline. For the full managed flow, run `omarchy update` instead.

AUR updates run through your helper (`yay -Sua` / `paru -Sua`) and Flatpak through `flatpak update`.

### AppImage

The AppImage row appears whenever at least one `*.AppImage` exists in the
de-facto AppImage locations: `~/Applications` (AppImageLauncher / Gear Lever
default), `~/.local/share/AppImage` (AppImagePool), `~/.local/bin`, or
`~/AppImages`. A `*.AppImage` symlinked into more than one of these is
counted once.
`~/Downloads` and `/opt` are intentionally not scanned (a staging area and a
root-owned system dir, respectively). The row needs
[`appimageupdatetool`](https://github.com/AppImageCommunity/AppImageUpdate)
(itself an AppImage) on `PATH`; if the tool is missing, the row shows an
**Install** button that downloads it into `~/Applications` and symlinks it
into `~/.local/bin` — user-local only, no root.

AppImages carry no package manager metadata: an update can only be detected for
AppImages that embed *update information* (most `gh-releases-zsync` / zsync
builds do). AppImages without it count toward the installed total but can never
report an available update — there is nothing to check them against.

Any AppImage whose check does not return a clean yes/no (no update info,
network error, or the tool crashing — see below) is reported as
`· N unchecked` instead of being silently treated as up to date.

Known upstream caveats with `appimageupdatetool` 2.0.0-alpha:

- Its GitHub-based (`gh-releases-zsync`) checks call the GitHub API
  **anonymously** — 60 requests/hour per IP. On a shared/corporate egress IP
  that bucket is often exhausted, and the check then fails with HTTP 403.
- On such failures the tool throws an **uncaught exception and aborts**
  (SIGABRT) instead of exiting cleanly, which produces a crash notification.
  The plugin absorbs this (the AppImage counts as *unchecked*), but the
  desktop notification originates from the tool itself.

The **AppImage** update button runs
`appimageupdatetool --overwrite --remove-old` over every AppImage in those
directories: each is updated in place and the `.zs-old` backup is removed after
a successful, signature-validated update.

The **Omarchy** update button opens your terminal and runs `omarchy update` — the full managed Omarchy update pipeline (transcript, snapshot, keyrings, migrations, and post-update hooks).

### Event-driven refresh

After clicking **Update**, the widget watches the Hyprland event socket (`Quickshell.Hyprland`) for the updater terminal to close, then rescans once immediately — no blind polling. A slow fallback poll (10s intervals) only runs if window tracking is unavailable. Repo reachability checks are consolidated into a single process and skipped entirely when NetworkManager reports no connectivity.

## Preview

![preview](preview.png)

## Uninstall

```sh
omarchy plugin remove dizziee.system-updates
```

## License

MIT
