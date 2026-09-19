# Project Skills

This directory contains skills integrated into this repository so Claude Code
can discover and use them automatically. The bulk come from the
[claude-skills](https://github.com/alirezarezvani/claude-skills) library, plus
individually vendored skills (see **Additional skills** below).

- **349 skills**, each in its own directory as `.claude/skills/<name>/SKILL.md`.
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

## Updating

These were vendored from the upstream repo. To refresh, re-clone upstream and
re-copy the skill directories (flattening collisions as above). Upstream also
supports native install via `/plugin marketplace add alirezarezvani/claude-skills`,
but vendoring here keeps the skills available in this repo's web/CI sessions
where user-level plugins do not persist.
