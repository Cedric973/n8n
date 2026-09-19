# Motion for React (framer-motion) — API Cheat-Sheet

Package: `motion` (new) / `framer-motion` (legacy alias), v13.
Import from `motion/react` (client), `motion/react-client` (RSC), or `motion` (plain JS/DOM).

## Components
- `motion.<element>` — animatable HTML/SVG element (`motion.div`, `motion.button`, `motion.path`, …)
- `motion.create(Component)` — make a custom/third-party component animatable (was `motion()`)
- `AnimatePresence` — enables `exit` animations for removed children (`mode`: "sync" | "wait" | "popLayout")
- `LazyMotion` + `m` — deferred/tree-shaken feature loading (`features={domAnimation | domMax}`)
- `MotionConfig` — set defaults (transition, reducedMotion) for a subtree
- `Reorder.Group` / `Reorder.Item` — drag-to-reorder lists
- `LayoutGroup` — group components that should share layout animation scope

## Animation props (on `motion.*`)
- `initial` — starting state (or `false` to disable mount animation)
- `animate` — target state (object or variant name)
- `exit` — state on unmount (requires `AnimatePresence`)
- `transition` — how to animate (see below)
- `variants` — named states map
- `whileHover`, `whileTap`, `whileFocus`, `whileDrag`, `whileInView` — gesture/viewport states
- `viewport` — `{ once, amount, margin, root }` for `whileInView`
- `layout` — `true | "position" | "size"` animate layout changes
- `layoutId` — shared-element transitions across locations
- `drag` — `true | "x" | "y"`; with `dragConstraints`, `dragElastic`, `dragMomentum`, `dragSnapToOrigin`
- `style` — accepts motion values
- `custom` — pass data to dynamic variants
- Lifecycle: `onAnimationStart`, `onAnimationComplete`, `onUpdate`, `onHoverStart/End`, `onTap`, `onDrag*`, `onViewportEnter/Leave`

## Transition options
- `type`: `"spring" | "tween" | "inertia"`
- spring: `stiffness`, `damping`, `mass`, `bounce`, `duration`, `visualDuration`
- tween: `duration`, `ease` (`"linear"|"easeIn"|"easeOut"|"easeInOut"|"circIn"|...|[cubic-bezier]`)
- `delay`, `repeat`, `repeatType` (`"loop"|"reverse"|"mirror"`), `repeatDelay`
- orchestration (on parent/variant): `when` (`"beforeChildren"|"afterChildren"`), `staggerChildren`, `delayChildren`, `staggerDirection`
- per-property overrides: `transition={{ x: {...}, opacity: {...} }}`

## Hooks
- `useAnimate()` → `[scope, animate]` — imperative/sequenced animations, scoped selectors
- `useMotionValue(initial)` — a value that animates without re-render
- `useTransform(value, input[], output[])` or `useTransform(() => ...)` — derive a motion value
- `useSpring(source | value, config)` — spring-smoothed motion value
- `useScroll({ target, container, offset })` → `{ scrollX, scrollY, scrollXProgress, scrollYProgress }`
- `useMotionValueEvent(value, "change"|"animationComplete"|..., cb)`
- `useMotionTemplate` — interpolate motion values into a template string
- `useVelocity(value)`, `useTime()`, `useAnimationFrame(cb)`
- `useInView(ref, options)` — boolean when element enters viewport
- `useReducedMotion()` — respect prefers-reduced-motion
- `useDragControls()`, `useAnimationControls()` (legacy imperative controls)

## Utilities / functions (from `motion`)
- `animate(target, keyframes, options)` — imperative animation (DOM selector, element, or value)
- `scroll(onScroll | animation, options)` — scroll-driven animation (plain JS)
- `inView(target, onStart, options)` — viewport callback (plain JS)
- `stagger(duration, { start, from, ease })` — stagger delays for `animate`
- `transform(input[], output[])` — standalone value mapper
- `spring(...)`, `frame`, `cancelFrame` — low-level helpers

## Feature bundles (for `LazyMotion`)
- `domAnimation` — animations, variants, gestures, exit (smaller)
- `domMax` — everything incl. layout animations + drag (larger)

## Common patterns
- Progress bar: `<motion.div style={{ scaleX: useScroll().scrollYProgress }} />`
- Reveal on scroll: `whileInView={{ opacity: 1, y: 0 }}` + `viewport={{ once: true }}`
- Shared tab underline: `<motion.div layoutId="underline" />` under the active tab
- Staggered list: parent `variants` with `staggerChildren` + child `variants`
- Page transition: `<AnimatePresence mode="wait">` keyed on route
