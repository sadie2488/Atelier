"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createRender, pollRender } from "./api";

export type RenderView = { local?: string; generated?: string; pending: boolean };

// Render on explicit action only (DECISIONS A-R1). Two-stage: show local_url at once, poll for
// generated_url, swap silently. Failures never surface: the local image (or plain avatar) stays.
export function useRender(avatarId: string | undefined) {
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<RenderView | null>(null);
  const ctlRef = useRef<AbortController | null>(null);

  const requestRender = useCallback((topId: string, bottomId: string, jacketId: string | null) => {
    if (!avatarId) return;
    ctlRef.current?.abort();
    const ctl = new AbortController();
    ctlRef.current = ctl;
    setLoading(true);
    setView(null);
    (async () => {
      try {
        const job = await createRender({ avatar_id: avatarId, top_id: topId, bottom_id: bottomId, jacket_id: jacketId });
        if (ctl.signal.aborted) return;
        setLoading(false);
        setView({ local: job.local_url, generated: job.generated_url ?? undefined, pending: job.status === "pending" });
        if (job.status !== "pending") return;
        const done = await pollRender(job.render_id, ctl.signal);
        if (ctl.signal.aborted) return;
        setView({ local: job.local_url, generated: done?.generated_url ?? undefined, pending: false });
      } catch {
        if (!ctl.signal.aborted) { setLoading(false); setView((v) => (v ? { ...v, pending: false } : null)); }
      }
    })();
  }, [avatarId]);

  // Cancel any in-flight render/poll and drop the current view.
  const clearRender = useCallback(() => { ctlRef.current?.abort(); setLoading(false); setView(null); }, []);

  useEffect(() => () => { ctlRef.current?.abort(); }, []);
  // Avatar switched (e.g. the demo toggle): drop any render made for the previous avatar.
  useEffect(() => { ctlRef.current?.abort(); setLoading(false); setView(null); }, [avatarId]);

  return { view, loading, requestRender, clearRender };
}
