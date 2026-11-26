import { motion } from 'motion/react';
import { AppIcon } from './AppIcon';
import type { IconName } from './AppIcon';

export function RailButton({ icon, title, active, label, count, onClick }: {
  icon: IconName;
  title: string;
  active?: boolean;
  label?: string;
  count?: number;
  onClick: () => void;
}) {
  return (
    <button type="button" className={`rail-button${icon === 'test' ? ' rail-test' : ''}`} title={title} aria-label={title} aria-pressed={active} onClick={onClick}>
      {active && <motion.span className="rail-active" layoutId="rail-active" transition={{ type: 'spring', stiffness: 360, damping: 33 }} />}
      <AppIcon name={icon} size={label ? 19 : 23} />
      {label && <span>{label}</span>}
      {count !== undefined && <b className="rail-count">{count}</b>}
    </button>
  );
}
