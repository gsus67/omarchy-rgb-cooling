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
