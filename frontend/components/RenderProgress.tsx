import type { RenderBar } from "@/lib/useRender";

// Thin bar along the bottom of the render frame: eases to ~90% over ~13 s while Nano Banana works,
// jumps to 100% and fades when the image arrives. Hidden for cached renders and on failure.
export function RenderProgress({ bar }: { bar: RenderBar }) {
  if (!bar) return null;
  return (
    <div className={`render-progress render-progress--${bar.phase}`} key={bar.id} role="progressbar" aria-label="styling your look">
      <span />
    </div>
  );
}
