#!/usr/bin/env bash
# Compatibility entry point. The supported install path is Omarchy's git plugin manager.
set -euo pipefail
exec omarchy plugin add https://github.com/gsus67/omarchy-rgb-cooling.git --enable "$@"
