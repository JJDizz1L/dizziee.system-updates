# dizziee.system-updates

System update indicator for the Omarchy bar. Shows available updates from pacman, AUR, and Flatpak, with per-repo update buttons.

## Requirements

- `checkupdates` (from `pacman-contrib`)
- AUR helper (`yay`, `paru`, etc.) — optional, AUR detection is automatic
- `flatpak` — optional

## Installation

```sh
git clone https://github.com/JJDizz1L/dizziee.system-updates.git ~/.config/omarchy/plugins/dizziee.system-updates
```

Then enable **System Updates** in the Omarchy bar widget settings.

## Configuration

| Key | Type | Default | Description |
|---|---|---|---|
| `refreshIntervalSec` | integer (300–7200) | 1800 | How often to check for updates (seconds) |
| `alwaysShow` | boolean | false | Keep icon visible even when no updates are available |

## License

MIT
