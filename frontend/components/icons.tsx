type IconProps = { size?: number; strokeWidth?: number };

function Icon({ size = 20, strokeWidth = 1.5, d }: IconProps & { d: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

export const ChevronLeft = (p: IconProps) => <Icon {...p} d="m15 18-6-6 6-6" />;
export const ChevronRight = (p: IconProps) => <Icon {...p} d="m9 18 6-6-6-6" />;
export const X = (p: IconProps) => <Icon {...p} d="M18 6 6 18M6 6l12 12" />;
export const Plus = (p: IconProps) => <Icon {...p} d="M5 12h14M12 5v14" />;
