---
name: design-md
description: >
  Extract, author, and apply DESIGN.md design-system files (TypeUI format) — the
  markdown blueprint AI coding agents use to build UI that matches a specific
  site's or brand's look. Use when the user wants to capture a website's design
  system (typography, colors, spacing, radius, shadows, motion) into a
  DESIGN.md or a design SKILL.md, wants UI that "looks like" a given site or
  brand, asks about the TypeUI DESIGN.md format or the "DESIGN.md Style
  Extractor" Chrome extension, or wants to write/validate a design-system
  skill by hand. Bundles the extension (loadable in Chrome) and its Node
  generators as references. For choosing an aesthetic from scratch use
  `frontend-design`; for Vue animation use `motion-v`.
---

# DESIGN.md — design-system blueprints for AI agents

`DESIGN.md` is a small markdown spec (the open [TypeUI DESIGN.md](https://www.typeui.sh/design-md)
format) that captures a design system — brand context, tokens, accessibility
rules, do/don't rules, and quality gates — so an agent can build UI that matches
it consistently. A `SKILL.md` variant is the same content with agent-skill
frontmatter so it activates automatically.

This skill wraps [bergside/design-md-chrome](https://github.com/bergside/design-md-chrome)
(MIT): a Chrome extension that reads any site's live styles and generates the
file, plus the Node generators it uses. The extension is vendored under
`references/extension/` and can be loaded straight into Chrome.

## When to use

- "Make our UI look like `<site>`" / "extract `<site>`'s design system"
- "Write a DESIGN.md for our brand" / "turn these tokens into a design skill"
- Reviewing or validating an existing DESIGN.md / design SKILL.md
- Producing a design system a tool like Claude Code, Codex, Cursor or Google
  Stitch can consume

## Two ways to get a DESIGN.md

### 1. Extract from a live site (Chrome extension)

Requires a real Chrome on the user's machine (not this sandbox):

1. Open `chrome://extensions`, enable **Developer mode**, click **Load unpacked**,
   and select `.claude/skills/design-md/references/extension/`.
2. Open the target site, click the extension → **Auto-extract** (reads typography,
   colors, spacing, radius, shadows, motion from the active tab).
3. **Generate `DESIGN.md`** or **Generate `SKILL.md`**, then **Download**.
   **Refresh** re-runs extraction; **?** explains how the file was built.

Permissions it needs: `activeTab`, `scripting`, `storage`, `downloads` (Manifest V3, v0.4.0).

### 2. Author by hand (or from tokens you already have)

Follow the blueprint in `references/DESIGN-BLUEPRINT.md`. Required structure:

```md
---
name: design-system-<brand-or-scope>
description: Creates implementation-ready design-system guidance with tokens, component behavior, and accessibility standards. Use when creating or updating UI rules, component specifications, or design-system documentation.
---
# <Design System Name>
## Mission            — one paragraph: objective + target product experience
## Brand              — product/brand, URL, audience, product surface
## Style Foundations  — visual style, main font, typography scale, color palette,
                        spacing scale, radius/shadow/motion tokens
## Accessibility      — WCAG 2.2 AA; keyboard-first; focus-visible; contrast
## Writing Tone       — concise, confident, implementation-focused
## Rules: Do          — semantic tokens (no raw hex); all states: default, hover,
                        focus-visible, active, disabled, loading, error; responsive + edge cases
## Rules: Don't       — no low-contrast text / hidden focus; no one-off spacing or
                        type exceptions; no ambiguous labels
## Guideline Authoring Workflow — intent → foundations → components → a11y → anti-patterns → QA
## Required Output Structure
## Component Rule Expectations  — keyboard/pointer/touch; spacing+type tokens; overflow/empty states
## Quality Gates      — "must" for non-negotiables, "should" for recommendations; testable a11y
```

Wrap the managed body in `<!-- TYPEUI_SH_MANAGED_START -->` / `<!-- TYPEUI_SH_MANAGED_END -->`
so a re-extraction can replace it without clobbering hand-written additions.

Acceptance checklist: valid frontmatter `name`/`description`; under ~500 lines;
states and a11y explicitly documented; rules concrete and testable; reusable in
another repo with only variable replacement.

## Generating programmatically (no browser)

The extension's generators are plain ES modules in `references/extension/lib/`
and run under Node with a normalized token object:

- `normalize.mjs` — normalizes raw extracted signals into `{ source, siteProfile,
  mainFontStyle, typographyScale, colorPalette, spacingScale, radiusTokens,
  shadowTokens, motionDurationTokens }`
- `generate-design-md.mjs` — emits `DESIGN.md`
- `generate-skill-md.mjs` — exports `generateSkillMarkdown({ normalized, metadata })`;
  `metadata` may set `systemName`, `brand`, `scope`, `audience`, `productSurface`
- `validate.mjs` — validates generated output

If you have tokens (e.g. from a CSS-variables file or a design-system package),
build the normalized object yourself and call the generator — no extension needed.

## Applying a DESIGN.md

- Put it at the repo root (`DESIGN.md`) or, as a skill, at
  `.claude/skills/design-system-<scope>/SKILL.md` so it auto-activates.
- When implementing UI against it: use its semantic tokens (never raw hex),
  implement every required state, and treat its Quality Gates as review criteria.

## In this repo (n8n)

n8n's design source of truth is `@n8n/design-system` plus the CSS variables in
`packages/frontend/CLAUDE.md` (`--color-*`, `--spacing-*`, `--font-*`,
`--border-radius-*`). A DESIGN.md for n8n should map its tokens to those
variables rather than inventing new ones, and any new pure Vue components
belong in `@n8n/design-system`. Pair with `frontend-design` (aesthetic
direction) and `motion-v` (animation).

## References

- `references/DESIGN-BLUEPRINT.md` — the canonical blueprint / format spec
- `references/extension/` — the loadable Chrome extension (source, `lib/` generators, README, LICENSE)
- TypeUI: https://www.typeui.sh/design-md · curated design skills: https://www.typeui.sh/design-skills
