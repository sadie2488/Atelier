"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "@/components/icons";
import { Loader, StatePanel } from "@/components/StatePanel";
import { CATEGORIES, generateOutfits, type Category, type Item } from "@/lib/api";
import { useItems, useStoredAvatar } from "@/lib/hooks";
import { useRender } from "@/lib/useRender";

type Lists = Record<Category, Item[]>;

const toFront = (list: Item[], id: string | null | undefined) => {
  const hit = id ? list.find((g) => g.id === id) : undefined;
  return hit ? [hit, ...list.filter((g) => g.id !== hit.id)] : list;
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
  const [notice, setNotice] = useState<"none" | "failed" | null>(null);
  const [noJacket, setNoJacket] = useState(false);

  // Lists keep the server's order (newest first); only "generate outfit" moves items to position 0.
  useEffect(() => {
    if (!itemsQ.items) return;
    const g = itemsQ.items;
    setLists({ tops: g.filter((x) => x.category === "tops"), bottoms: g.filter((x) => x.category === "bottoms"), jackets: g.filter((x) => x.category === "jackets") });
  }, [itemsQ.items]);

  // Render only right after "generate outfit" positions the lists; never on swipe or selection change.
  const { view, loading, requestRender, clearRender } = useRender(avatar?.avatar_id);

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

  const generate = async () => {
    setBusy(true); setNotice(null);
    try {
      const outfits = await generateOutfits(5);
      const best = outfits[0];
      if (!best) { setNotice("none"); return; }
      setLists({ tops: toFront(lists.tops, best.top_id), bottoms: toFront(lists.bottoms, best.bottom_id), jackets: toFront(lists.jackets, best.jacket_id) });
      setIdx({ tops: 0, bottoms: 0, jackets: 0 });
      setNoJacket(!best.jacket_id);
      setExplanation(best.explanation);
      setWhy({ strategy: best.strategy, score: best.score });
      // Render right away for the top-ranked outfit just positioned at index 0.
      requestRender(best.top_id, best.bottom_id, best.jacket_id ?? null);
    } catch { setNotice("failed"); }
    finally { setBusy(false); }
  };

  const shown = view?.generated ?? view?.local ?? (loading ? avatar.wireframe_url : avatar.avatar_url);

  return (
    <main className="stylist-page" aria-label="Stylist">
      <div className="stylist-lists">
        {CATEGORIES.filter((c) => !(noJacket && c === "jackets")).map((c) => {
          const cur = lists[c][idx[c] ?? 0];
          return (
            <div className="swipe-list" key={c}>
              <button type="button" aria-label={`Previous ${c}`} onClick={() => swipe(c, -1)} disabled={lists[c].length < 2}><ChevronLeft size={18} /></button>
              <div className="swipe-item">
                {cur ? <img src={cur.cutout_url} alt={cur.retailer_item_name ?? c} /> : <span className="swipe-empty">no {c}</span>}
                <small>{c} {lists[c].length ? `${(idx[c] ?? 0) + 1}/${lists[c].length}` : ""}</small>
              </div>
              <button type="button" aria-label={`Next ${c}`} onClick={() => swipe(c, 1)} disabled={lists[c].length < 2}><ChevronRight size={18} /></button>
            </div>
          );
        })}
      </div>

      <div className="stylist-avatar">
        <div className={`stylist-avatar-box${view?.pending ? " render-frame--pending" : ""}`}>
          <img key={shown} className={`render-img${view?.generated && shown === view.generated ? " render-img--generated" : ""}`} src={shown} alt="Your avatar wearing this outfit" />
        </div>
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
        <button type="button" className={`stylist-action${noJacket ? " is-on" : ""}`} aria-pressed={noJacket} onClick={() => { setNoJacket((v) => !v); clearRender(); }}>{noJacket ? "with jacket" : "no jacket"}</button>
        {notice === "none" && <p className="stylist-note">No good combinations from this closet yet. Add a few more pieces.</p>}
        {notice === "failed" && <p className="stylist-note">The stylist couldn&apos;t compose a look just now. Try again in a moment.</p>}
      </div>
    </main>
  );
}
