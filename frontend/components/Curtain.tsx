"use client";

import { useState } from "react";

// Covers the whole render frame while a try-on is being generated. When `up` falls, the curtain
// lifts with a short reveal (a plain fade under prefers-reduced-motion) and then unmounts.
export function Curtain({ up, children }: { up: boolean; children?: React.ReactNode }) {
  const [prevUp, setPrevUp] = useState(up);
  const [leaving, setLeaving] = useState(false);
  if (up !== prevUp) {
    setPrevUp(up);
    setLeaving(!up && prevUp);
  }
  if (!up && !leaving) return null;
  return (
    <div className={`curtain${leaving ? " curtain--leaving" : ""}`} aria-hidden={leaving} onAnimationEnd={(e) => { if (e.target === e.currentTarget && leaving) setLeaving(false); }}>
      <div className="curtain-content">{children}</div>
    </div>
  );
}
