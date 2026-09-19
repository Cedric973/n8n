---
name: motion-v
description: >
  Add animations, gestures, and transitions to Vue 3 UIs with Motion for Vue
  (npm `motion-v`, currently v2) — the Vue port of Motion/Framer Motion. Use when
  the user wants to animate Vue components: enter/exit transitions, hover/tap/drag
  gestures, scroll-linked or scroll-triggered effects, shared-element/layout
  animations, staggered lists, spring physics, or number tweening. This is the
  RIGHT animation skill for this n8n repo's Vue frontend (`editor-ui`,
  `@n8n/design-system`) — use it instead of `framer-motion` (React-only) whenever
  the target is a `.vue` component. Covers the `motion` components and `<Motion>`
  element, variants, `AnimatePresence`, motion values (`useScroll`/`useTransform`/
  `useSpring`), layout animations, gestures, and reduced-motion/performance best practices.
---

# Motion for Vue (motion-v)

Animation library for **Vue 3** — the Vue port of Motion (Framer Motion). Same
mental model as Motion for React, expressed with Vue templates and composables.
Current major: **v2**. Repo: https://github.com/motiondivision/motion-vue,
docs: https://motion.dev/docs/vue.

> In this repo, n8n's frontend is Vue 3 — put pure animatable components in
> `@n8n/design-system` where reusable, follow `packages/frontend/CLAUDE.md` for
> CSS variables, and animate `transform`/`opacity` (not layout properties) for perf.

## Install & import

```bash
npm i motion-v
```

```ts
import { motion, AnimatePresence } from "motion-v";
```

No global plugin is required — import the components where you use them. (A Nuxt
module also exists for auto-import; for plain Vite/Vue just import directly.)

## Core: the `motion` component

Every element has a `motion` version. It animates from `initial` to `animate`;
`exit` runs on unmount inside `<AnimatePresence>`. Props are bound (kebab-case in template).

```vue
<script setup lang="ts">
import { motion } from "motion-v";
</script>

<template>
  <motion.div
    :initial="{ opacity: 0, y: 20 }"
    :animate="{ opacity: 1, y: 0 }"
    :exit="{ opacity: 0, y: -20 }"
    :transition="{ duration: 0.4, ease: 'easeOut' }"
    :while-hover="{ scale: 1.05 }"
    :while-tap="{ scale: 0.95 }"
    :while-in-view="{ opacity: 1 }"
    :in-view-options="{ once: true, amount: 0.3 }"
  />
</template>
```

Equivalent element form (useful for dynamic tags):
```vue
<Motion as="div" :animate="{ x: 100 }" />
```

## Variants — named states + stagger

```vue
<script setup lang="ts">
import { motion } from "motion-v";
const list = { hidden: {}, visible: { transition: { staggerChildren: 0.08, delayChildren: 0.2 } } };
const item = { hidden: { opacity: 0, y: 10 }, visible: { opacity: 1, y: 0 } };
</script>

<template>
  <motion.ul :variants="list" initial="hidden" animate="visible">
    <motion.li v-for="t in items" :key="t" :variants="item">{{ t }}</motion.li>
  </motion.ul>
</template>
```
`initial`/`animate` accept a variant name (string) as well as an object.

## Exit animations — `<AnimatePresence>`

Wrap conditionally-rendered elements so `exit` plays before removal. Children need a stable `:key`.

```vue
<AnimatePresence mode="wait">     <!-- "sync" | "wait" | "popLayout" -->
  <motion.div
    v-if="open" key="panel"
    :initial="{ opacity: 0 }" :animate="{ opacity: 1 }" :exit="{ opacity: 0 }"
  />
</AnimatePresence>
```

## Transitions

```ts
:transition="{ type: 'spring', stiffness: 300, damping: 30 }"     // physics
:transition="{ type: 'tween', duration: 0.3, ease: [0.4, 0, 0.2, 1] }"
:transition="{ duration: 0.5, delay: 0.1, repeat: Infinity, repeatType: 'reverse' }"
```

## Motion values, scroll & composables

Composables mirror the React hooks.

```vue
<script setup lang="ts">
import { motion, useScroll, useTransform } from "motion-v";
const { scrollYProgress } = useScroll();
const scale = useTransform(scrollYProgress, [0, 1], [0.8, 1]);
</script>

<template>
  <motion.div :style="{ scaleX: scrollYProgress }" />   <!-- progress bar -->
</template>
```

Composables: `useMotionValue`, `useTransform`, `useSpring`, `useScroll`,
`useMotionValueEvent`, `useVelocity`, `useTime`, `useAnimationFrame`,
`useInView`, `useReducedMotion`, `useAnimate` (imperative/sequenced).

## Layout & gestures

```vue
<motion.div layout />                                  <!-- animate layout changes -->
<motion.div layout-id="underline" />                   <!-- shared-element transition -->

<motion.div
  drag                                                 <!-- or drag="x" / drag="y" -->
  :drag-constraints="{ left: 0, right: 300 }"
  :while-drag="{ scale: 1.1 }"
/>
```

Extra components: `<LayoutGroup>`, `<Reorder.Group>` / `<Reorder.Item>` (drag reorder),
`<MotionConfig>` (subtree defaults, incl. `reducedMotion`), `<AnimateNumber>` (tween numbers).

## Best practices

- **Perf:** animate `transform` (x, y, scale, rotate) and `opacity`; avoid `width`/`height`/`top`/`left` — use `layout` or `scale`.
- **Accessibility:** honor `useReducedMotion()` (or `<MotionConfig :reduced-motion="'user'">`).
- **Keys:** every `AnimatePresence` child / `v-for` item needs a stable `:key`.
- **This repo:** use CSS variables from `packages/frontend/CLAUDE.md` for any styling; keep reusable animated pieces in `@n8n/design-system`; all UI text via `@n8n/i18n`.

## References

- `references/api-cheatsheet.md` — components, composables, props at a glance.
- Docs: https://motion.dev/docs/vue
