# Security

Please report vulnerabilities privately through
[GitHub security advisories](https://github.com/gsus67/omarchy-rgb-cooling/security/advisories/new)
instead of a public issue.

Design rules (see [docs/PROMPT.md](docs/PROMPT.md)):

- The QML UI is unprivileged and never touches hardware.
- `rgbcd` runs as a socket-activated `systemd --user` service, never as root,
  and never writes PWM or hardware registers. Fan curves run in the cooling
  engine (CoolerControl) or in firmware.
- The socket is `0600` in `$XDG_RUNTIME_DIR`, and every connection is checked
  with `SO_PEERCRED`. The API accepts only a closed set of operations with
  validated parameters.
- Engine credentials live only in `0600` files, never in URLs or command lines.
- Text coming from devices or engines is always rendered as plain text.
- The plugin never installs packages or runs `sudo` on its own.

Every change to `main` must pass, in CI:

- Python tests (including static QML checks) and the native self-tests;
- the same native self-tests under AddressSanitizer and UndefinedBehaviorSanitizer;
- a clean-uninstall test: install into a throwaway home, uninstall, and fail
  if anything the project created is left behind;
- `systemd-analyze verify` and a `systemd-analyze security` threshold for every unit;
- CodeQL `security-extended` for C++, Python and the workflows;
- ShellCheck for the scripts and zizmor for the workflows;
- OpenSSF Scorecard (weekly and on `main`).

Every security fix ships with a regression test that would have caught it.
