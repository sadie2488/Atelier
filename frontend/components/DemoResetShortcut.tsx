"use client";

import { useEffect } from "react";
import { resetDemo } from "@/lib/demoReset";

// Ctrl+Shift+Alt+R anywhere: confirm, reset the demo, go home.
export function DemoResetShortcut() {
  useEffect(() => {
    const onKey = async (e: KeyboardEvent) => {
      if (!(e.ctrlKey && e.shiftKey && e.altKey && e.key.toLowerCase() === "r")) return;
      e.preventDefault();
      if (!window.confirm("Reset the demo to default? (closet back to the demo items; stylist defaults cleared; saved outfits kept)")) return;
      try {
        const r = await resetDemo();
        window.alert(`Demo reset: ${r.items} items, ${r.archived.length} archived, ${r.restored.length} restored.`);
        window.location.href = "/";
      } catch (err) { window.alert(err instanceof Error ? err.message : "Reset failed."); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return null;
}
