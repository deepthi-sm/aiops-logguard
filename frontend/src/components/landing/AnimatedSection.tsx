import { motion, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";
import { useInView } from "react-intersection-observer";

// Framer Motion v11 wants `ease` typed as a 4-tuple cubic bezier; the
// `as const` makes the literal a tuple instead of a number[].
export const EASE_OUT_CUBIC = [0.16, 1, 0.3, 1] as const;

/**
 * Wraps a landing-page section so it fades + slides into view on first
 * scroll-in. Restraint: 30 px slide max, 600 ms duration, ease-out
 * cubic. Only triggers once. `prefers-reduced-motion: reduce` removes
 * all motion (sections appear instantly).
 */
interface Props {
  children: ReactNode;
  direction?: "left" | "right" | "up";
  delay?: number;
  id?: string;
  className?: string;
}

export function AnimatedSection({
  children,
  direction = "up",
  delay = 0,
  id,
  className,
}: Props) {
  // 0.3 — animation triggers when 30% of the section is in view, so it
  // feels like it fires when you've actually arrived rather than ahead
  // of the scroll.
  const { ref, inView } = useInView({ threshold: 0.3, triggerOnce: true });
  const reducedMotion = useReducedMotion();

  const initial = reducedMotion
    ? { opacity: 1, x: 0, y: 0 }
    : {
        opacity: 0,
        x: direction === "left" ? -30 : direction === "right" ? 30 : 0,
        y: direction === "up" ? 30 : 0,
      };

  return (
    <motion.section
      id={id}
      ref={ref}
      className={className}
      initial={initial}
      animate={inView ? { opacity: 1, x: 0, y: 0 } : initial}
      transition={{ duration: 0.8, ease: EASE_OUT_CUBIC, delay }}
    >
      {children}
    </motion.section>
  );
}

/**
 * Stagger variants for child elements within a section. Each child
 * appears 80 ms after the previous one, with a small fade + lift.
 * Apply by giving the parent `containerVariants` and each child
 * `itemVariants` and `motion.div` (or similar).
 */
export const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08 } },
};

export const itemVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};
