"use client";

import { useState } from "react";
import { resetDemo, type ResetResult } from "@/lib/demoReset";

// Secret dev page: /reset (not linked anywhere).
export default function ResetPage() {
  const [state, setState] = useState<"idle" | "busy" | ResetResult | string>("idle");
  const run = async () => {
    setState("busy");
    try { setState(await resetDemo()); } catch (e) { setState(e instanceof Error ? e.message : "Reset failed."); }
  };
  return (
    <main className="flow-page" aria-label="Reset demo">
      <div style={{ display: "grid", gap: 16, justifyItems: "center", textAlign: "center", maxWidth: 420, margin: "20vh auto 0" }}>
        <h1 style={{ font: "italic 500 32px var(--font-display)", margin: 0 }}>Reset demo</h1>
        <p style={{ margin: 0, color: "var(--muted-foreground)" }}>Closet back to the demo items; stylist defaults and the demo switch cleared (saved outfits are kept).</p>
        {state === "idle" && <button type="button" className="solid-btn" onClick={run}>Reset to default</button>}
        {state === "busy" && <p>Resetting…</p>}
        {typeof state === "object" && (
          <>
            <p>Done: {state.items} items. Archived {state.archived.length}, restored {state.restored.length}.</p>
            <a className="ghost-btn" href="/">back to home</a>
          </>
        )}
        {typeof state === "string" && state !== "idle" && state !== "busy" && <p role="alert">{state}</p>}
      </div>
    </main>
  );
}
