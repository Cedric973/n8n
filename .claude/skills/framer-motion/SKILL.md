---
name: framer-motion
description: >
  Add animations, gestures, and transitions to React UIs with Motion for React
  (the library formerly named Framer Motion; npm packages `motion` and
  `framer-motion`, currently v13). Use when the user wants to animate React
  components — enter/exit transitions, hover/tap/drag gestures, scroll-linked or
  scroll-triggered effects, shared-element/layout animations, staggered lists,
  spring physics, or page transitions — or asks how to use framer-motion / motion.
  Covers the `motion` components, variants, `AnimatePresence`, motion values
  (`useScroll`/`useTransform`/`useSpring`), layout animations, gestures, the
  imperative `animate()` function, and bundle-size + reduced-motion best practices.
  NOTE: this is a React library. For plain JS/DOM use `animate()` from `motion`;
  for Vue (e.g. this n8n repo's `editor-ui`) use the separate `motion-v` package,
  not this one.
---

# Motion for React (framer-motion)

Production-ready animation library for React. Formerly **Framer Motion**; now
also published as **`motion`**. Import from `motion/react`. Current major: **v13**.

## Install & import

```bash
npm i motion          # new name (recommended)
# or the legacy alias, same code:
npm i framer-motion
```

```jsx
import { motion, AnimatePresence } from "motion/react";   // React (client)
// Legacy import path still works: import { motion } from "framer-motion";
// React Server Components: import * as motion from "motion/react-client";
// Plain JS / DOM (no React): import { animate, scroll } from "motion";
```

## When to use

- Enter/exit transitions, hover/tap/focus/drag gestures
- Scroll-linked (parallax, progress bars) or scroll-triggered (reveal-on-view) effects
- Shared-element transitions and automatic layout animations (reordering, resizing)
- Staggered lists, spring physics, page/route transitions

For a static fade or a one-off hover, plain CSS transitions may be enough — reach
for Motion when you need orchestration, gestures, spring physics, layout, or exit
animations (which CSS can't do on unmount).

## Core: the `motion` component

Any element gets a `motion` version with animation props. It animates from
`initial` to `animate`, and `exit` runs on unmount (inside `AnimatePresence`).

```jsx
<motion.div
  initial={{ opacity: 0, y: 20 }}
  animate={{ opacity: 1, y: 0 }}
  exit={{ opacity: 0, y: -20 }}
  transition={{ duration: 0.4, ease: "easeOut" }}
  whileHover={{ scale: 1.05 }}
  whileTap={{ scale: 0.95 }}
  whileInView={{ opacity: 1 }}        // animate when scrolled into view
  viewport={{ once: true, amount: 0.3 }}
/>
```

Custom components: wrap with `motion.create()` (v12+; was `motion()`):
```jsx
const MotionLink = motion.create(Link);
```

## Variants — named states + orchestration

Variants let a parent drive children and enable staggering.

```jsx
const list = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08, delayChildren: 0.2 } },
};
const item = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0 },
};

<motion.ul variants={list} initial="hidden" animate="visible">
  {items.map((t) => <motion.li key={t} variants={item}>{t}</motion.li>)}
</motion.ul>
```

## Exit animations — `AnimatePresence`

Wrap conditionally-rendered elements so `exit` runs before removal. Children need a stable `key`.

```jsx
<AnimatePresence mode="wait">     {/* "wait" | "sync" | "popLayout" */}
  {open && (
    <motion.div key="panel" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
  )}
</AnimatePresence>
```

## Transitions

```jsx
transition={{ type: "spring", stiffness: 300, damping: 30 }}   // physics-based
transition={{ type: "tween", duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
transition={{ duration: 0.5, delay: 0.1, repeat: Infinity, repeatType: "reverse" }}
// Per-property: transition={{ opacity: { duration: 0.2 }, y: { type: "spring" } }}
```

## Motion values & scroll

Motion values track animating state without re-rendering. `useTransform` maps one
to another; `useScroll` gives scroll progress; `useSpring` smooths a value.

```jsx
import { useScroll, useTransform, motion } from "motion/react";

const { scrollYProgress } = useScroll();                 // 0→1 over page
const scale = useTransform(scrollYProgress, [0, 1], [0.8, 1]);
return <motion.div style={{ scaleX: scrollYProgress }} />;  // progress bar
```

Other hooks: `useMotionValue`, `useVelocity`, `useMotionValueEvent(value, "change", cb)`,
`useMotionTemplate` (compose values into a string, e.g. `filter`).

## Layout animations

`layout` animates size/position changes automatically; `layoutId` animates a shared
element between two rendered locations (tabs, expanding cards).

```jsx
<motion.div layout />                                  {/* animate layout changes */}
{tabs.map((t) => (
  <button key={t} onClick={() => setActive(t)}>
    {t}
    {active === t && <motion.div layoutId="underline" className="underline" />}
  </button>
))}
```

## Gestures — drag

```jsx
<motion.div
  drag                              // or drag="x" / drag="y"
  dragConstraints={{ left: 0, right: 300 }}
  dragElastic={0.2}
  whileDrag={{ scale: 1.1 }}
/>
```

## Imperative animation — `useAnimate`

For sequences, event-driven animations, or animating non-style things.

```jsx
import { useAnimate } from "motion/react";
const [scope, animate] = useAnimate();
// later: await animate(scope.current, { x: 100 }, { duration: 0.3 });
//        animate("li", { opacity: 1 }, { delay: stagger(0.1) });  // scoped selector
```

Plain DOM (no React): `import { animate } from "motion"; animate("#box", { x: 100 })`.

## Best practices

- **Performance:** prefer animating `transform` (x, y, scale, rotate) and `opacity` —
  they're GPU-friendly and don't trigger layout. Avoid animating `width`/`height`/`top`/`left`;
  use `layout` or `scale` instead.
- **Bundle size:** for size-sensitive apps use `LazyMotion` with `domAnimation` (or
  `domMax` for layout/drag) and the `m` component instead of `motion` to defer/shrink the feature bundle.
- **Accessibility:** respect `useReducedMotion()` — disable or soften large motion when the user prefers reduced motion.
- **Keys:** every `AnimatePresence` child and list item needs a stable, unique `key` or exit/stagger breaks.

## References

- `references/api-cheatsheet.md` — components, hooks, props, and exports at a glance.
- Docs: https://motion.dev/docs/react
- Repo: https://github.com/motiondivision/motion
