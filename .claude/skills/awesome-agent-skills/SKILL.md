---
name: awesome-agent-skills
description: >
  Find the right agent skill for a task from a local, searchable index of
  1,497+ curated skills (VoltAgent's awesome-agent-skills list: official skills
  from Anthropic, Stripe, Google, Vercel, and vetted community/engineering-team
  skills, with their install links). Use when the user asks "is there a skill
  for X", wants to discover or compare skills/plugins for a tool, framework, or
  workflow, or asks what's available beyond this repo's own skills base. Works
  offline — the index is vendored — so it replaces googling for tools. After a
  pick, integrate it into `.claude/skills/` the way the rest of this base was
  built. Not for using a skill that's already installed here — check
  `.claude/skills/` first.
---

# Awesome Agent Skills — local skill finder

A vendored snapshot of [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)
(MIT): a hand-picked index of 1,497+ agent skills — official ones from
Anthropic, Stripe, Google, Vercel and other dev teams, plus vetted community
skills — each linking to its repo and install method. Compatible with Claude
Code, Codex, Gemini CLI, Cursor and more.

The index lives at `references/INDEX.md` (snapshot taken 2026-09-20).

## When to use

- "Is there a skill for `<X>`?" / "what skills exist for `<framework>`?"
- Comparing options before adding a skill to this repo's base
- Discovering official skills for a vendor (Stripe, Supabase, Vercel, …)

## Check what's already here first

This repo already vendors a large base under `.claude/skills/` (the
claude-skills library, gstack, Anthropic's official skills, taste, and more —
see `.claude/skills/README.md`). Before hunting, `ls .claude/skills/` and grep
its README; the answer is often already installed.

## How to search the index

The index is markdown with HTML sections. `###` headings are the top groups
(Official Skills by…, Core, per-language, Community Skills). Inside them, each
vendor or sub-category is a collapsible block —
`<details><summary><h3 …>Skills by Stripe Team</h3></summary>` — and every
skill is a bullet: `- **[owner/repo](url)** - one-line description`. Search by
keyword, then read the surrounding lines:

```bash
IDX=.claude/skills/awesome-agent-skills/references/INDEX.md

# find skills mentioning a keyword (case-insensitive), with context
grep -in "stripe" "$IDX"
grep -in -B2 -A2 "playwright" "$IDX"

# list every vendor / sub-category section
grep -oE 'summary><h3[^>]*>[^<]+' "$IDX" | sed 's/.*>//'

# list only the top-level groups
grep -E '^### ' "$IDX"
```

Present matches as: **name — one-line purpose — source/owner — install link**.
Prefer official/vendor-maintained entries over community ones when both exist,
and say which is which.

## Integrating a pick

This base vendors skills into the repo (so they persist in web/CI sessions
where user-level installs don't). When the user picks one:

1. Clone it and inspect: find its `SKILL.md`(s), size, and whether it is a
   plain skill, a suite, or a plugin with bundled code.
2. Vendor under `.claude/skills/<frontmatter-name>/` (nested tree for suites),
   omit demo assets/tests, and keep runtime scripts.
3. Check for name collisions against the whole base and disambiguate with a
   prefix if needed; verify no duplicate frontmatter names remain.
4. Update `.claude/skills/README.md`, commit, push.

## Security — read before installing anything

Skills run instructions and often code inside your agent. Per the list's own
Security Notice: vet a skill before installing — read its `SKILL.md` and any
scripts, prefer official sources, check the repo's activity and license, and
never install something that asks for credentials or broad permissions it
doesn't need. A vendored copy here is a snapshot: re-check upstream for
changes before trusting new versions.

## Refreshing the index

```bash
git clone --depth 1 https://github.com/VoltAgent/awesome-agent-skills /tmp/aas \
  && cp /tmp/aas/README.md .claude/skills/awesome-agent-skills/references/INDEX.md
```
Then update the snapshot date above.
