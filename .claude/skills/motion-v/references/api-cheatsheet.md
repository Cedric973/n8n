# Motion for Vue (motion-v) — API Cheat-Sheet

Package: `motion-v`, v2. Vue 3 only. Import from `motion-v`.
Props in templates are bound and kebab-cased (`:while-hover`, `layout-id`).

## Components
- `motion.<element>` — animatable element (`motion.div`, `motion.button`, `motion.svg`, …)
- `<Motion as="div">` — element form with dynamic tag via `as`
- `<AnimatePresence>` — enables `exit` for removed children (`mode`: "sync" | "wait" | "popLayout")
- `<LayoutGroup>` — shared layout animation scope
- `<Reorder.Group>` / `<Reorder.Item>` — drag-to-reorder lists (`v-model` on group)
- `<MotionConfig>` — subtree defaults (`:transition`, `:reduced-motion`)
- `<AnimateNumber>` — animate/tween a numeric value

## Animation props (on `motion.*` / `<Motion>`)
- `:initial` — starting state (or `:initial="false"` to skip mount animation)
- `:animate` — target state (object or variant name string)
- `:exit` — unmount state (inside `<AnimatePresence>`)
- `:transition` — timing/physics
- `:variants` — named states map
- `:while-hover`, `:while-tap`, `:while-focus`, `:while-drag`, `:while-in-view`
- `:in-view-options` — `{ once, amount, margin, root }` for while-in-view
- `layout` — `true | "position" | "size"`
- `layout-id` — shared-element transitions
- `drag` — `true | "x" | "y"`; `:drag-constraints`, `:drag-elastic`, `:drag-momentum`, `:drag-snap-to-origin`
- `:style` — accepts motion values
- `:custom` — data for dynamic variants
- Events: `@animation-start`, `@animation-complete`, `@update`, `@hover-start/@hover-end`, `@tap`, `@drag-start/@drag/@drag-end`, `@view-enter/@view-leave`

## Transition options
- `type`: `"spring" | "tween" | "inertia"`
- spring: `stiffness`, `damping`, `mass`, `bounce`, `duration`, `visualDuration`
- tween: `duration`, `ease` (keyword or `[cubic-bezier]`)
- `delay`, `repeat`, `repeatType` (`"loop"|"reverse"|"mirror"`), `repeatDelay`
- orchestration: `when`, `staggerChildren`, `delayChildren`, `staggerDirection`
- per-property overrides: `:transition="{ x: {...}, opacity: {...} }"`

## Composables
- `useAnimate()` → `[scope, animate]` — imperative/sequenced, scoped selectors
- `useMotionValue(initial)`
- `useTransform(value, input[], output[])` or `useTransform(() => ...)`
- `useSpring(source, config)`
- `useScroll({ target, container, offset })` → `{ scrollX, scrollY, scrollXProgress, scrollYProgress }`
- `useMotionValueEvent(value, "change"|..., cb)`
- `useMotionTemplate` — interpolate motion values into a string
- `useVelocity`, `useTime`, `useAnimationFrame`
- `useInView(target, options)` — reactive boolean on viewport enter
- `useReducedMotion()`

## Common patterns
- Progress bar: `<motion.div :style="{ scaleX: useScroll().scrollYProgress }" />`
- Reveal on scroll: `:while-in-view="{ opacity: 1, y: 0 }"` + `:in-view-options="{ once: true }"`
- Shared tab underline: `<motion.div layout-id="underline" />` under active tab
- Staggered list: parent `:variants` with `staggerChildren` + child `:variants` over `v-for`
- Route transition: `<AnimatePresence mode="wait">` keyed on route

## Notes vs framer-motion (React)
- Same concepts; templates use `:prop` binding + kebab-case, events use `@event`.
- No JSX — use `<motion.div>` or `<Motion as="...">` in template.
- Composables return refs/motion values usable directly in `:style`.
