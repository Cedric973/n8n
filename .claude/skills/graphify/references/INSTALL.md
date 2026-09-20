# graphify — install requirement

This skill drives the `graphify` command-line tool; it does **not** work on its
own. The CLI (PyPI package **`graphifyy`**) must be installed and on `PATH`.

```bash
# Recommended (uv):
uv tool install graphifyy && graphify install
# Run without installing:
uvx graphifyy install
```

`graphify install` is what normally provisions this SKILL.md + references into
`~/.claude/skills/graphify/`. Here they are vendored into the repo directly so the
skill is discoverable in this repo's sessions — but building/querying graphs still
requires the `graphify` CLI (and, for graph building, an LLM API key) on the
machine that runs it.

- Package: `graphifyy` (CLI entry points: `graphify`, `graphify-mcp`)
- Upstream: https://github.com/safishamsi/graphify
- Typical use: `/graphify .` to build a graph, then `graphify query "<question>"`.

Note: in a restricted-network sandbox the CLI's repo-clone and model-download
steps may be blocked; run it where outbound access and an API key are available.
