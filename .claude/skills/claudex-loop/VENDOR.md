# Vendored dependency

These four sibling skills — `claudex-loop`, `claudex-route`, `codex-build`
and `codex-review` — are vendored verbatim from a third-party project. They
are not maintained in this repository.

| | |
|---|---|
| Upstream | https://github.com/chaseai-yt/claudex-loop |
| Version | 2.1.0 |
| Commit | `8cf5e2c1771c5151d90c12642391d0ba8fa71b0e` |
| License | MIT (see `LICENSE`) |
| Vendored | 2026-09-19 |

## Layout

`codex-build` and `codex-review` resolve shared references through relative
paths (`../claudex-loop/references/`), so all four directories must stay
siblings under `.claude/skills/`.

## Requirements

The workflow runs two providers against each other, so it needs **both** the
`claude` and `codex` CLIs installed and authenticated on PATH. With only one
of them, `scripts/runner.py` exits with
`<provider> is not on PATH. Install and authenticate its CLI first.`

## Updating

Re-copy `skills/*` from upstream and refresh the commit and version above.
Do not patch these files in place — local edits will be lost on the next sync.
