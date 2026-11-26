import { useMotionValue, useReducedMotion, useSpring } from 'motion/react';
import { useEffect, useRef } from 'react';
import type { PointerEvent } from 'react';

const spring = { stiffness: 150, damping: 21, mass: 0.7 };

function normalized(value: number, start: number, length: number) {
  return Math.max(-1, Math.min(1, (value - start) / Math.max(1, length) * 2 - 1));
}

export function usePointerDepth() {
  const reducedMotion = useReducedMotion();
  const bounds = useRef<DOMRect | null>(null);
  const pointerX = useMotionValue(0);
  const pointerY = useMotionValue(0);
  const x = useSpring(pointerX, spring);
  const y = useSpring(pointerY, spring);

  useEffect(() => {
    if (!reducedMotion) return;
    bounds.current = null;
    pointerX.jump(0);
    pointerY.jump(0);
    x.jump(0);
    y.jump(0);
  }, [pointerX, pointerY, reducedMotion, x, y]);

  function move(event: PointerEvent<HTMLElement>) {
    if (!bounds.current || reducedMotion || event.pointerType !== 'mouse') return;
    const { left, top, width, height } = bounds.current;
    pointerX.set(normalized(event.clientX, left, width));
    pointerY.set(normalized(event.clientY, top, height));
  }

  function enter(event: PointerEvent<HTMLElement>) {
    if (reducedMotion || event.pointerType !== 'mouse') return;
    bounds.current = event.currentTarget.getBoundingClientRect();
    move(event);
  }

  function reset() {
    bounds.current = null;
    pointerX.set(0);
    pointerY.set(0);
  }

  return { x, y, handlers: { onPointerEnter: enter, onPointerMove: move, onPointerLeave: reset, onPointerCancel: reset } };
}
