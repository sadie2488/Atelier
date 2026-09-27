"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createRender, pollRender } from "./api";

export type RenderView = { local?: string; generated?: string; pending: boolean };
// Progress bar state: shown only while a non-cached render is being generated.
export type RenderBar = { id: number; phase: "running" | "done" } | null;
// Result of a deferred render: the finished view, a failure, or cancelled (superseded / cleared).
export type RenderOutcome = { ok: true; view: RenderView } | { ok: false; aborted: boolean };

// Render on explicit action only (DECISIONS A-R1). Two-stage: poll for generated_url, swap silently.
// Failures never surface as errors: the previous image (or plain avatar) stays.
// `keep: true` leaves the current view untouched while waiting; the caller commits the result
// itself with commitView (so it can update the rest of its page in the same render).
export function useRender(avatarId: string | undefined) {
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<RenderView | null>(null);
  const [bar, setBar] = useState<RenderBar>(null);
  const ctlRef = useRef<AbortController | null>(null);
  const barId = useRef(0);

  const requestRender = useCallback((topId: string, bottomId: string, jacketId: string | null, opts?: { keep?: boolean }): Promise<RenderOutcome> => {
    const keep = !!opts?.keep;
    if (!avatarId) return Promise.resolve({ ok: false, aborted: false });
    ctlRef.current?.abort();
    const ctl = new AbortController();
    ctlRef.current = ctl;
    setBar(null);
    if (!keep) { setLoading(true); setView(null); }
    // The render POST itself can take a few seconds: start the bar if it hasn't answered within
    // 600 ms (a cached render answers faster and never shows the bar).
    const id = ++barId.current;
    const early = window.setTimeout(() => { if (!ctl.signal.aborted) setBar({ id, phase: "running" }); }, 600);
    ctl.signal.addEventListener("abort", () => window.clearTimeout(early));
    return (async (): Promise<RenderOutcome> => {
      try {
        const job = await createRender({ avatar_id: avatarId, top_id: topId, bottom_id: bottomId, jacket_id: jacketId });
        window.clearTimeout(early);
        if (ctl.signal.aborted) return { ok: false, aborted: true };
        const first: RenderView = { local: job.local_url, generated: job.generated_url ?? undefined, pending: job.status === "pending" };
        if (!keep) { setLoading(false); setView(first); }
        if (job.status !== "pending") {
          // Already generated (cached / prewarmed): no progress bar.
          setBar(null);
          return first.generated ? { ok: true, view: first } : { ok: false, aborted: false };
        }
        setBar({ id, phase: "running" }); // same id: an already-running bar keeps its progress
        const done = await pollRender(job.render_id, ctl.signal);
        if (ctl.signal.aborted) return { ok: false, aborted: true };
        const final: RenderView = { local: job.local_url, generated: done?.generated_url ?? undefined, pending: false };
        setBar(final.generated ? { id, phase: "done" } : null);
        if (!keep) setView(final);
        return final.generated ? { ok: true, view: final } : { ok: false, aborted: false };
      } catch {
        window.clearTimeout(early);
        if (ctl.signal.aborted) return { ok: false, aborted: true };
        setBar(null);
        if (!keep) { setLoading(false); setView((v) => (v ? { ...v, pending: false } : null)); }
        return { ok: false, aborted: false };
      }
    })();
  }, [avatarId]);

  const commitView = useCallback((v: RenderView | null) => setView(v), []);

  // Cancel any in-flight render/poll and drop the current view.
  const clearRender = useCallback(() => { ctlRef.current?.abort(); setLoading(false); setView(null); setBar(null); }, []);
  // Cancel any in-flight render/poll but keep what's on screen.
  const cancelRender = useCallback(() => { ctlRef.current?.abort(); setLoading(false); setBar(null); }, []);

  useEffect(() => () => { ctlRef.current?.abort(); }, []);
  // Avatar switched (e.g. the demo toggle): drop any render made for the previous avatar.
  useEffect(() => { ctlRef.current?.abort(); setLoading(false); setView(null); setBar(null); }, [avatarId]);

  return { view, loading, bar, requestRender, commitView, clearRender, cancelRender };
}
