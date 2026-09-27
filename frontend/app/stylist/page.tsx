"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "@/components/icons";
import { Loader, StatePanel } from "@/components/StatePanel";
import { CATEGORIES, DEMO_OUTFITS, generateOutfits, type Category, type Item } from "@/lib/api";
import { useDemoToggle, useItems, useStoredAvatar } from "@/lib/hooks";
import { RenderProgress } from "@/components/RenderProgress";
import { useRender } from "@/lib/useRender";
import { Curtain } from "@/components/Curtain";
import { SavedOutfitsPanel } from "@/components/SavedOutfitsPanel";
import { useSavedOutfits, type SavedOutfit } from "@/lib/savedOutfits";

type Lists = Record<Category, Item[]>;

const toFront = (list: Item[], id: string | null | undefined) => {
  const hit = id ? list.find((g) => g.id === id) : undefined;
  return hit ? [hit, ...list.filter((g) => g.id !== hit.id)] : list;
};

// The closet's outfit tray (sessionStorage), carried one way into the stylist on load.
type Tray = Partial<Record<"top" | "bottom" | "jacket", string>>;
const readTray = (): Tray => {
  try { const v = sessionStorage.getItem("atelier:outfit-tray"); return v ? (JSON.parse(v) as Tray) : {}; } catch { return {}; }
};

// Plain-words label for a strategy code, e.g. "neutral_anchor" -> "neutral anchor".
const strategyLabel = (strategy: string) => strategy.replace(/_/g, " ");

export default function StylistPage() {
  const avatar = useStoredAvatar();
  const itemsQ = useItems();
  const [lists, setLists] = useState<Lists | null>(null);
  const [idx, setIdx] = useState<Record<Category, number>>({ tops: 0, bottoms: 0, jackets: 0 });
  const [explanation, setExplanation] = useState<string | null>(null);
  const [why, setWhy] = useState<{ strategy: string; score: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<"none" | "failed" | "render" | null>(null);
  const [noJacket, setNoJacket] = useState(false);
  const trayApplied = useRef(false);
  const saved = useSavedOutfits();
  const [savedOpen, setSavedOpen] = useState(false);
  const [savedFlash, setSavedFlash] = useState(0); // >0 while the "Saved" confirmation shows
  const closeSaved = useCallback(() => setSavedOpen(false), []);
  const byId = useMemo(() => new Map((itemsQ.items ?? []).map((g) => [g.id, g] as const)), [itemsQ.items]);
  useEffect(() => {
    if (!savedFlash) return;
    const t = window.setTimeout(() => setSavedFlash(0), 1600);
    return () => window.clearTimeout(t);
  }, [savedFlash]);
  const demo = useDemoToggle();
  const plannedIdx = useRef(0); // next planned demo outfit (cycles)
  // Toggling the demo avatar restarts the planned sequence and drops the old explanation.
  useEffect(() => { plannedIdx.current = 0; setExplanation(null); setWhy(null); }, [demo.on]);

  // Lists keep the server's order (newest first); only "generate outfit" moves items to position 0.
  useEffect(() => {
    if (!itemsQ.items) return;
    const g = itemsQ.items;
    const base: Lists = { tops: g.filter((x) => x.category === "tops"), bottoms: g.filter((x) => x.category === "bottoms"), jackets: g.filter((x) => x.category === "jackets") };
    // Put the closet's tray pieces at index 0 whenever the lists are (re)built; no render (renders stay explicit).
    const tray = readTray();
    setLists({ tops: toFront(base.tops, tray.top), bottoms: toFront(base.bottoms, tray.bottom), jackets: toFront(base.jackets, tray.jacket) });
    if (!trayApplied.current && (tray.top || tray.bottom || tray.jacket)) {
      trayApplied.current = true;
      setIdx({ tops: 0, bottoms: 0, jackets: 0 });
      setNoJacket(!(tray.jacket && base.jackets.some((x) => x.id === tray.jacket)));
    }
  }, [itemsQ.items]);

  // Render only right after "generate outfit" positions the lists; never on swipe or selection change.
  const { view, bar, requestRender, commitView, clearRender } = useRender(avatar?.avatar_id);

  if (avatar === undefined || itemsQ.isPending) return <main className="flow-page"><Loader label="Setting up the studio…" /></main>;
  if (avatar === null) return (
    <main className="flow-page"><StatePanel title="No avatar yet" actions={<Link href="/scan" className="solid-btn">scan yourself</Link>}>The stylist dresses your avatar. Take a quick scan first.</StatePanel></main>
  );
  if (itemsQ.isError || !lists) return (
    <main className="flow-page"><StatePanel title="The studio is out of reach" actions={<button type="button" className="solid-btn" onClick={itemsQ.refetch}>try again</button>}>We couldn&apos;t load your garments right now.</StatePanel></main>
  );

  const tooSmall = lists.tops.length === 0 || lists.bottoms.length === 0;

  // Swiping never calls /api/render — it just clears a stale render (clearRender cancels any in-flight poll).
  const swipe = (c: Category, d: number) => {
    const n = lists[c].length;
    if (!n) return;
    setIdx((p) => ({ ...p, [c]: (((p[c] ?? 0) + d) % n + n) % n }));
    setExplanation(null);
    setWhy(null);
    clearRender();
  };

  // Nothing on the page changes until Nano Banana's image is ready: the current still, the lists
  // and the explanation stay put while we wait; then everything updates at once.
  // On failure the page stays exactly as it was, with a calm note.
  const generate = async () => {
    setBusy(true); setNotice(null);
    try {
      let pick: { top_id: string; bottom_id: string; jacket_id: string | null };
      let text: { explanation: string; strategy: string; score: number } | null = null;
      if (demo.on && DEMO_OUTFITS.length) {
        // Demo: planned outfits in order (cycling); explanation only if the generator returned the same combo.
        const plan = DEMO_OUTFITS[plannedIdx.current % DEMO_OUTFITS.length];
        plannedIdx.current += 1;
        const outfits = await generateOutfits(5).catch(() => []);
        const hit = outfits.find((o) => o.top_id === plan.top_id && o.bottom_id === plan.bottom_id && (o.jacket_id ?? null) === plan.jacket_id);
        pick = { top_id: plan.top_id, bottom_id: plan.bottom_id, jacket_id: plan.jacket_id };
        if (hit) text = { explanation: hit.explanation, strategy: hit.strategy, score: hit.score };
      } else {
        const outfits = await generateOutfits(5);
        const best = outfits[0];
        if (!best) { setNotice("none"); return; }
        pick = { top_id: best.top_id, bottom_id: best.bottom_id, jacket_id: best.jacket_id ?? null };
        text = { explanation: best.explanation, strategy: best.strategy, score: best.score };
      }
      const out = await requestRender(pick.top_id, pick.bottom_id, pick.jacket_id, { keep: true });
      if (!out.ok) { if (!out.aborted) setNotice("render"); return; }
      // Commit everything in one go (React batches these into a single paint).
      commitView(out.view);
      setLists((cur) => cur && { tops: toFront(cur.tops, pick.top_id), bottoms: toFront(cur.bottoms, pick.bottom_id), jackets: toFront(cur.jackets, pick.jacket_id) });
      setIdx({ tops: 0, bottoms: 0, jackets: 0 });
      setNoJacket(!pick.jacket_id);
      setExplanation(text?.explanation ?? null);
      setWhy(text ? { strategy: text.strategy, score: text.score } : null);
    } catch { setNotice("failed"); }
    finally { setBusy(false); }
  };

  // The outfit currently on screen (what "save outfit" stores).
  const curTop = lists.tops[idx.tops ?? 0], curBottom = lists.bottoms[idx.bottoms ?? 0];
  const curJacket = noJacket ? undefined : lists.jackets[idx.jackets ?? 0];
  const saveCurrent = () => {
    if (!curTop || !curBottom) return;
    if (saved.save({ top_id: curTop.id, bottom_id: curBottom.id, jacket_id: curJacket?.id ?? null, image_url: view?.generated ?? null, explanation })) setSavedFlash((n) => n + 1);
  };

  // Load a saved outfit: position the lists like generate does and show its saved try-on, if any.
  // Never starts a render.
  const wearSaved = (o: SavedOutfit) => {
    clearRender();
    setNotice(null);
    setLists((cur) => cur && { tops: toFront(cur.tops, o.top_id), bottoms: toFront(cur.bottoms, o.bottom_id), jackets: toFront(cur.jackets, o.jacket_id) });
    setIdx({ tops: 0, bottoms: 0, jackets: 0 });
    setNoJacket(!o.jacket_id);
    if (o.image_url) commitView({ generated: o.image_url, pending: false });
    setExplanation(o.explanation ?? null);
    setWhy(null);
    setSavedOpen(false);
  };

  const shown = view?.generated ?? avatar.avatar_url; // only the Nano Banana image or the plain avatar, never the coordinate-placed preview

  return (
    <main className="stylist-page" aria-label="Stylist">
      <div className="stylist-lists">
        {CATEGORIES.map((c) => {
          const cur = lists[c][idx[c] ?? 0];
          const toggle = c === "jackets" && (
            <button type="button" className={`jacket-toggle${noJacket ? " is-on" : ""}`} aria-pressed={noJacket} onClick={() => { setNoJacket((v) => !v); clearRender(); }}>{noJacket ? "with jacket" : "no jacket"}</button>
          );
          if (c === "jackets" && noJacket) return <div className="jacket-block" key={c}>{toggle}</div>;
          const row = (
            <div className="swipe-list" key={c}>
              <button type="button" aria-label={`Previous ${c}`} onClick={() => swipe(c, -1)} disabled={lists[c].length < 2}><ChevronLeft size={18} /></button>
              <div className="swipe-item">
                {cur ? <img src={cur.cutout_url} alt={cur.retailer_item_name ?? c} /> : <span className="swipe-empty">no {c}</span>}
                <small>{c} {lists[c].length ? `${(idx[c] ?? 0) + 1}/${lists[c].length}` : ""}</small>
              </div>
              <button type="button" aria-label={`Next ${c}`} onClick={() => swipe(c, 1)} disabled={lists[c].length < 2}><ChevronRight size={18} /></button>
            </div>
          );
          return toggle ? <div className="jacket-block" key={c}>{row}{toggle}</div> : row;
        })}
      </div>

      <div className="stylist-avatar">
        <div className={`stylist-avatar-box${busy ? " render-frame--pending" : ""}${view?.generated ? " render-frame--generated" : ""}`}>
          <img key={shown} className={`render-img${view?.generated && shown === view.generated ? " render-img--generated" : ""}`} src={shown} alt="Your avatar wearing this outfit" />
          {/* Curtain only while a non-cached render is being generated (the bar shows exactly then). */}
          <Curtain up={busy && !!bar}><p className="curtain-text">styling your look…</p></Curtain>
          <RenderProgress bar={bar} />
        </div>
        <p className="render-status" aria-live="polite">{busy && !bar ? "styling your look…" : savedFlash ? "Saved" : " "}</p>
        {explanation && <p className="stylist-explain">{explanation}</p>}
        {why && <p className="stylist-why">why this works: {strategyLabel(why.strategy)} &middot; {Math.round(why.score * 100)}%</p>}
      </div>

      <div className="stylist-actions">
        <Link href="/insights" className="stylist-action">palette insights</Link>
        {tooSmall ? (
          <div className="stylist-note"><p>Your closet needs at least a top and a bottom to build an outfit.</p><Link href="/add-item" className="stylist-action">add item</Link></div>
        ) : (
          <button type="button" className="stylist-action" onClick={generate} disabled={busy}>{busy ? "styling…" : "generate outfit"}</button>
        )}
        {!tooSmall && <button type="button" className="stylist-action" onClick={saveCurrent} disabled={busy || !curTop || !curBottom}>{savedFlash ? "saved" : "save outfit"}</button>}
        <button type="button" className="stylist-action" onClick={() => setSavedOpen(true)}>saved outfits{saved.outfits.length ? ` (${saved.outfits.length})` : ""}</button>
        {notice === "none" && <p className="stylist-note">No good combinations from this closet yet. Add a few more pieces.</p>}
        {notice === "render" && <p className="stylist-note">Couldn&apos;t style this one just now. Generate again in a moment.</p>}
        {notice === "failed" && <p className="stylist-note">The stylist couldn&apos;t compose a look just now. Try again in a moment.</p>}
      </div>
      {savedOpen && <SavedOutfitsPanel outfits={saved.outfits} byId={byId} onPick={wearSaved} onRemove={saved.remove} onClose={closeSaved} />}
    </main>
  );
}
