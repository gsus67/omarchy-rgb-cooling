# Contributing

- Work happens on a branch and lands on `main` only through a pull request,
  squash-merged with a clean title (`feat: ...`, `fix: ...`, `docs: ...`).
- `main` is protected: every required check must be green, the branch must be
  up to date, history stays linear, and admins follow the same rules.
- One phase or adapter per pull request; follow [docs/PROMPT.md](docs/PROMPT.md).
- Clean work: whatever the project adds to a system (files, units, sockets,
  state, caches, engine exclusions) is tracked and removed by `uninstall.sh`,
  and when a feature or file is dropped, the next bootstrap removes what older
  versions left behind. The "Clean uninstall" check enforces this.
- Every security fix comes with a regression test.
- Actions are pinned by commit SHA; Dependabot keeps them updated.

## Adding your motherboard's fan header names

Fan channels show as `Fan N` until `data/fan-headers.json` has a verified entry
for your exact board. To add one:

1. Load your board's hwmon driver (for MSI NCT6687D boards:
   `sudo modprobe nct6683 force=1`) and note which `fanN_input` channels spin
   (`grep . /sys/class/hwmon/hwmon*/fan*_input`).
2. Check in the BIOS hardware monitor, or by moving a fan between headers,
   which header each spinning channel is on.
3. Copy your identity exactly from `/sys/class/dmi/id/board_vendor` and
   `/sys/class/dmi/id/board_name`, and the chip from the hwmon `name` file.
4. Add an entry with `"status": "user-verified"`, a `verified` note saying what
   you checked, your `sources`, and only the channels you could confirm.
   Header names use the board's silkscreen (`SYS_FAN1`, `CPU_FAN1`…).

CI validates the file against the same schema rgbcd uses. Never copy another
board's entry: the same chip is wired differently from board to board.
