/**
 * Gauntlet Animation System
 * Warm spring animations + Framer Motion presets
 */

// ---- SPRING PRESETS ----

export const spring = {
  type: 'spring',
  mass: 1,
  stiffness: 120,
  damping: 14,
}

export const springFast = {
  type: 'spring',
  mass: 0.5,
  stiffness: 250,
  damping: 22,
}

export const springBouncy = {
  type: 'spring',
  mass: 0.8,
  stiffness: 150,
  damping: 10,
}

export const springSnappy = {
  type: 'spring',
  stiffness: 400,
  damping: 30,
}

// ---- STAGGER CONTAINERS ----

export const staggerContainer = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: {
      staggerChildren: 0.06,
      delayChildren: 0.1,
    },
  },
}

export const staggerItem = {
  hidden: { opacity: 0, y: 24 },
  show: {
    opacity: 1,
    y: 0,
    transition: spring,
  },
}

// ---- REVEAL ANIMATIONS ----

export const fadeSlideUp = {
  initial: { opacity: 0, y: 30 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -16 },
  transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] },
}

export const scaleIn = {
  initial: { scale: 0, opacity: 0 },
  animate: { scale: 1, opacity: 1 },
  transition: springBouncy,
}

export const slideFromLeft = {
  initial: { x: -50, opacity: 0 },
  animate: { x: 0, opacity: 1 },
  transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] },
}

// ---- BAR / CHART ANIMATIONS ----

export const barGrow = (delay = 0) => ({
  initial: { scaleX: 0 },
  animate: { scaleX: 1 },
  transition: { ...spring, delay },
})

// ---- PAGE TRANSITIONS ----

export const pageTransition = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -6 },
  transition: { duration: 0.3, ease: [0.22, 1, 0.36, 1] },
}

// ---- MODEL COLORS (warm, muted, professional) ----

export const MODEL_COLORS = [
  '#7d93ab', // steel blue
  '#b08d6e', // bronze
  '#6ea882', // sage
  '#c4a05a', // gold
  '#a87c94', // mauve
  '#c27065', // terracotta
  '#5da4a8', // teal
  '#9b8e78', // khaki
]

export const getModelColor = (index) => MODEL_COLORS[index % MODEL_COLORS.length]

// ---- EASING ----

export const EASING = {
  smooth:   [0.16, 1, 0.3, 1],
  snappy:   [0.22, 1, 0.36, 1],
  material: [0.4, 0, 0.2, 1],
}
