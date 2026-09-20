# Project Skills

This directory contains skills integrated into this repository so Claude Code
can discover and use them automatically. The bulk come from the
[claude-skills](https://github.com/alirezarezvani/claude-skills) library, plus
individually vendored skills (see **Additional skills** below).

- **440 skills** (372 flat + the 59-skill gstack suite + the 9-skill
  understand-anything suite), each an `.claude/skills/<name>/SKILL.md` (the gstack
  and understand-anything suites are nested under their own directories, discovered
  recursively).
- Skills are flattened to one directory per skill (Claude Code discovers direct
  children of `.claude/skills/`). The 17 skills whose names collided across
  source domains are prefixed with their domain, e.g.
  `engineering__status`, `c-level-advisor__vpe-advisor`.
- Each `SKILL.md` carries `name` + `description` frontmatter that drives
  automatic activation; supporting `scripts/`, `references/`, and `assets/`
  live alongside it.

## Domains included

engineering, engineering-team, c-level-advisor, marketing-skill, ra-qm-team,
product-team, project-management, compliance-os, commercial,
business-operations, productivity, markdown-html, business-growth, finance,
marketing, research, research-ops.

## Additional skills

Vendored individually from their own repos (not part of the claude-skills library):

- **scroll-world** — builds a scroll-scrubbed "fly through the world" landing
  page via Higgsfield. From [oso95/scroll-world](https://github.com/oso95/scroll-world).
- **crawl4ai** — crawl/scrape websites into LLM-ready Markdown or structured
  JSON using the [unclecode/crawl4ai](https://github.com/unclecode/crawl4ai)
  Python library. Authored here (the upstream repo ships a library, not a
  `SKILL.md`); the skill wraps its install, async API, extraction strategies,
  deep crawling, and CLI.
- **browser-skill** — drive the user's real, logged-in Chromium browser (visit
  pages, fill forms, scrape, click through flows) via the `bsk` CLI + browser
  extension. From [Tencent/BrowserSkill](https://github.com/Tencent/BrowserSkill).
  Requires installing the `bsk` CLI and extension separately — see
  `browser-skill/references/AGENT_INSTALL.md`.
- **framer-motion** — animate React UIs with Motion for React (formerly Framer
  Motion; npm `motion` / `framer-motion`, v13): transitions, gestures, scroll and
  layout animations, motion values. Authored here (upstream ships an npm library,
  not a `SKILL.md`). React-only — for Vue use `motion-v` instead.
- **motion-v** — animate Vue 3 UIs with Motion for Vue (npm `motion-v`, v2): the
  Vue port of Motion. **This is the animation skill that applies to this repo's
  Vue frontend** (`editor-ui`, `@n8n/design-system`). Authored here (upstream
  ships an npm library, not a `SKILL.md`).
- **gstack** — Garry Tan's opinionated Claude Code suite of 59 skills (CEO/`cso`,
  `review`, `qa`, `ship`, `office-hours`, `design-review`, `spec`, planning,
  iOS, docs, etc.) vendored as a nested tree under `.claude/skills/gstack/`. From
  [garrytan/gstack](https://github.com/garrytan/gstack) (full tree minus the
  `test/` fixtures). The three skills whose names collided with existing ones were
  renamed `gstack-review`, `gstack-office-hours`, `gstack-freeze`. NOTE: upstream
  is meant to be installed via its own `./setup` (which builds a `browse` browser
  binary and registers commands); that build step was **not** run here, so skills
  that shell out to the built binary or expect a user-level install may need
  `./setup` run in `.claude/skills/gstack/` first.
- **stop-slop** — strip predictable AI-writing tells (em-dashes, "it's not X,
  it's Y", hollow intros) from prose when drafting/editing/reviewing. From
  [hardikpandya/stop-slop](https://github.com/hardikpandya/stop-slop).
- **graphify** — turn any folder of code/SQL/docs/papers/media into a queryable
  knowledge graph ("real memory") and answer codebase questions from the graph.
  From [safishamsi/graphify](https://github.com/safishamsi/graphify) — the Claude
  skill body + references (what `graphify install` deploys). REQUIRES the CLI:
  `uv tool install graphifyy && graphify install`. See
  `graphify/references/INSTALL.md`. Without the CLI the skill is discoverable but
  can't build/query graphs.

- **understand-anything** — builds an interactive, explorable map/knowledge graph
  of any unfamiliar codebase (every file, function, data flow). 9 skills vendored
  as a nested tree under `.claude/skills/understand-anything/`: `understand`,
  `understand-onboard`, `understand-explain`, `understand-chat`,
  `understand-dashboard`, `understand-diff`, `understand-domain`,
  `understand-figma`, `understand-knowledge`. From
  [Egonex-AI/Understand-Anything](https://github.com/Egonex-AI/Understand-Anything)
  (the `understand-anything-plugin/` tree, incl. its `packages/`, `agents/`, `hooks/`
  and `src/`, minus node_modules). NOTE: the skills shell out to bundled Node
  packages and reference `${CLAUDE_PLUGIN_ROOT}`; no prebuilt `dist/` ships, so
  full graph/dashboard features need `pnpm install && build` inside
  `.claude/skills/understand-anything/` on a machine that can run it.
- **last30days** — research what people actually said about any topic in the
  last 30 days across Reddit, X, YouTube, TikTok, Hacker News, Polymarket,
  GitHub and the web, ranked by real engagement; includes a `doctor` health
  check for sources. Use: `/last30days <topic>`. From
  [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill)
  (v3.25.0). Packaged per upstream's `.skillignore`: the 14 MB demo `assets/`,
  `agents/` and dev/eval scripts are omitted; runtime `scripts/` (incl. the
  vendored X-search client) are kept. Live searches need outbound network
  access and per-source API keys — see `CONFIGURATION.md` upstream.
- **frontend-design** — Anthropic's official design skill: picks a real
  aesthetic direction (typography, color, motion, layout) and ships
  distinctive, production-grade UI instead of templated "AI-looking" defaults.
  Auto-applies when building or reshaping UI. From
  [anthropics/skills](https://github.com/anthropics/skills)
  (`skills/frontend-design`, incl. its LICENSE.txt). For this repo's Vue
  frontend, pair it with `motion-v` for animation and the CSS variables in
  `packages/frontend/CLAUDE.md`.
- **Anthropic official skills (17 more)** — the rest of
  [anthropics/skills](https://github.com/anthropics/skills), vendored as-is:
  `academy-guide`, `algorithmic-art`, `canvas-design`, `discernment-nudge`,
  `doc-coauthoring`, `docx`, `mcp-builder`, `pdf`, `pptx`, `skill-creator`,
  `slack-gif-creator`, `theme-factory`, `web-artifacts-builder`,
  `webapp-testing`, `xlsx`, plus `anthropic-brand-guidelines` and
  `anthropic-internal-comms` (prefixed because the claude-skills library already
  provides skills named `brand-guidelines` and `internal-comms`; the official
  Anthropic versions are the `anthropic-` ones). Deliberately **omitted**:
  `claude-api`, which only works against the paid Anthropic API. `docx`/`pptx`/
  `xlsx`/`pdf` bundle helper scripts that need their Python/Node deps installed;
  `webapp-testing` needs Playwright; `slack-gif-creator` targets Slack.
- **design-md** — extract, author, and apply `DESIGN.md` design-system files
  (TypeUI format) so UI matches a given site or brand. Authored here on top of
  [bergside/design-md-chrome](https://github.com/bergside/design-md-chrome)
  (MIT), a Chrome extension that reads any site's live styles and generates
  `DESIGN.md` / design `SKILL.md`. The extension is vendored, loadable, under
  `design-md/references/extension/` ("Load unpacked" in Chrome), with its Node
  generators (`lib/`) usable without a browser and the canonical format
  blueprint at `design-md/references/DESIGN-BLUEPRINT.md`. Note: extracting
  from a live site needs a real Chrome on your machine.

## Updating

These were vendored from the upstream repo. To refresh, re-clone upstream and
re-copy the skill directories (flattening collisions as above). Upstream also
supports native install via `/plugin marketplace add alirezarezvani/claude-skills`,
but vendoring here keeps the skills available in this repo's web/CI sessions
where user-level plugins do not persist.
