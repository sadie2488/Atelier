"use client";

// Secret dev reset: closet back to the demo default (backend/demo_baseline.json; reversible archive)
// and this browser's demo state cleared. Triggers: Ctrl+Shift+Alt+R anywhere, or the /reset page.
const RESET_KEY = "atelier-demo-reset";
const LOCAL_KEYS = ["atelier:stylist-defaults", "atelier:demo-avatar"]; // saved outfits are kept (Gemini-outage backup)
const SESSION_KEYS = ["atelier:outfit-tray"];

export type ResetResult = { ok: true; archived: string[]; restored: string[]; items: number };

export async function resetDemo(): Promise<ResetResult> {
  const res = await fetch(`/api/demo/reset?key=${encodeURIComponent(RESET_KEY)}`, { method: "POST" });
  if (!res.ok) throw new Error(`Reset failed (${res.status})`);
  const out = (await res.json()) as ResetResult;
  for (const k of LOCAL_KEYS) { try { localStorage.removeItem(k); } catch { /* storage unavailable */ } }
  for (const k of SESSION_KEYS) { try { sessionStorage.removeItem(k); } catch { /* storage unavailable */ } }
  return out;
}
