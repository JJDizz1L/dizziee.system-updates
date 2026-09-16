#!/usr/bin/env bash
# Install appimageupdatetool: the official AppImage from the AppImageUpdate
# project's continuous release, linked onto PATH. Entirely user-local:
# no root, no package manager, nothing outside ~/Applications + ~/.local/bin.
set -euo pipefail

case "$(uname -m)" in
  x86_64) arch=x86_64 ;;
  aarch64 | arm64) arch=aarch64 ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

url="https://github.com/AppImageCommunity/AppImageUpdate/releases/download/continuous/appimageupdatetool-${arch}.AppImage"
target="$HOME/Applications/appimageupdatetool-${arch}.AppImage"
link="$HOME/.local/bin/appimageupdatetool"

mkdir -p "$HOME/Applications" "$HOME/.local/bin"
echo "Downloading $url"
curl -fL --progress-bar -o "$target" "$url"
chmod +x "$target"
ln -sf "$target" "$link"
echo "Installed: $link -> $target"

if ! "$link" --version 2>&1; then
  echo
  echo "The tool downloaded but failed to run. AppImages need FUSE 2:" >&2
  echo "  sudo pacman -S --needed fuse2" >&2
fi
