// Pose outline / wireframe figure: standing, front-facing, arms slightly away from the body.
export function PoseFigure({ className = "", mesh = false }: { className?: string; mesh?: boolean }) {
  return (
    <svg className={className} viewBox="0 0 200 400" fill="none" aria-hidden="true">
      <g stroke="currentColor" strokeWidth={mesh ? 1 : 2} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={mesh ? undefined : "6 6"}>
        <ellipse cx="100" cy="42" rx="22" ry="27" />
        <path d="M88 68 L86 82 L62 90 Q52 94 50 108 L38 200 L46 204 L64 118 L68 170 L66 250 L74 380 L94 380 L98 250 L102 250 L106 380 L126 380 L134 250 L132 170 L136 118 L154 204 L162 200 L150 108 Q148 94 138 90 L114 82 L112 68" />
        {mesh && (
          <>
            <path d="M68 120 H132 M66 170 H134 M66 210 H134 M70 290 H96 M104 290 H130 M72 340 H94 M106 340 H128" />
            <path d="M100 82 V250 M84 90 L80 250 M116 90 L120 250" />
            <path d="M56 140 L48 150 M144 140 L152 150" />
          </>
        )}
      </g>
    </svg>
  );
}
