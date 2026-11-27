import { useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react';
import { motion, useIsPresent, useReducedMotion } from 'motion/react';

const settle = [0.22, 0.75, 0.26, 1] as const;

export function OperatorRoutePane({ children, activeDesk, scrollTop, moved }: {
  children: ReactNode;
  activeDesk: RefObject<HTMLDivElement | null>;
  scrollTop: number;
  moved: boolean;
}) {
  const pane = useRef<HTMLDivElement>(null);
  const present = useIsPresent();
  const reduced = useReducedMotion();

  useLayoutEffect(() => {
    const element = pane.current;
    if (!element || !present) return;

    activeDesk.current = element;
    element.scrollTop = scrollTop;
    if (moved && !element.contains(document.activeElement)) element.focus({ preventScroll: true });
    return () => { if (activeDesk.current === element) activeDesk.current = null; };
  }, [activeDesk, moved, present, scrollTop]);

  return (
    <motion.div
      ref={pane}
      tabIndex={-1}
      className="desk operator-route"
      data-route-exiting={!present || undefined}
      data-route-moved={moved || undefined}
      inert={!present}
      initial={reduced ? false : { opacity: 0, y: 7 }}
      animate={{ opacity: 1, y: 0, transition: { duration: reduced ? 0 : .27, delay: reduced ? 0 : .035, ease: settle } }}
      exit={{ opacity: 0, y: reduced ? 0 : -3, transition: { duration: reduced ? 0 : .14, ease: 'easeOut' } }}
    >
      {children}
    </motion.div>
  );
}
