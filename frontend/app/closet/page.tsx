"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/Button";
import { Plus, X } from "@/components/icons";
import { Carousel, type Study } from "@/components/closet/Carousel";
import { Loader, StatePanel } from "@/components/StatePanel";
import { CATEGORIES, type Category, type ExtractedColor, type Item } from "@/lib/api";
import { useIsMobile, useItems, useStoredAvatar } from "@/lib/hooks";
import { useRender } from "@/lib/useRender";

type ClosetStudy = Study & { items: Item[]; type: string };
type Slot = "top" | "bottom" | "jacket";
type Tray = Partial<Record<Slot, string>>;

// Dresses are tops, so category alone decides the slot.
const SLOT_OF: Record<Category, Slot> = { tops: "top", bottoms: "bottom", jackets: "jacket" };
const SLOTS: Slot[] = ["top", "bottom", "jacket"];
const TRAY_KEY = "atelier:outfit-tray";

function readTray(): Tray {
  try { const v = sessionStorage.getItem(TRAY_KEY); return v ? (JSON.parse(v) as Tray) : {}; } catch { return {}; }
}
function writeTray(t: Tray) {
  try { sessionStorage.setItem(TRAY_KEY, JSON.stringify(t)); } catch { /* storage unavailable */ }
}

function SwatchChip({ color, label }: { color: ExtractedColor; label: string }) {
  return (
    <div className="swatch">
      <span className="swatch-color" style={{ background: color.hex }} />
      <span><small>{label}</small>{color.display_name ?? color.name}{color.is_neutral ? <em className="neutral-tag">neutral</em> : color.everyday_neutral ? <em className="neutral-tag">everyday neutral</em> : null}</span>
    </div>
  );
}

export default function ClosetPage() {
  const isMobile = useIsMobile();
  const itemsQ = useItems();
  const avatar = useStoredAvatar();
  const [cats, setCats] = useState([0, 1]);
  const [detail, setDetail] = useState<Item | null>(null);
  const [tray, setTray] = useState<Tray>({});
  const [renderOpen, setRenderOpen] = useState(false);
  const { view, loading, requestRender, clearRender } = useRender(avatar?.avatar_id);

  useEffect(() => { setTray(readTray()); }, []);
  const updateTray = (next: Tray) => { setTray(next); writeTray(next); };
  const closeRender = () => { setRenderOpen(false); clearRender(); };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") { setDetail(null); setRenderOpen(false); } };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // The server's order is authoritative (newest first); never re-sort here.
  const items = itemsQ.items ?? [];
  const collection: ClosetStudy[] = CATEGORIES.map((c, i) => {
    const inCategory = items.filter((g) => g.category === c);
    return { name: c.toUpperCase(), title: "", images: inCategory.map((g) => g.cutout_url), index: `0${i + 1}`, type: c, items: inCategory };
  });

  // Drop ids that are no longer in the closet.
  const byId = new Map(items.map((g) => [g.id, g] as const));
  const trayItem = (slot: Slot) => { const id = tray[slot]; return id ? byId.get(id) : undefined; };
  const trayTop = trayItem("top"), trayBottom = trayItem("bottom"), trayJacket = trayItem("jacket");
  const trayFilled = SLOTS.some((s) => trayItem(s));
  const canRender = !!trayTop && !!trayBottom;

  // Rendering happens only on this explicit press (never on add/remove).
  const seeItOnMe = () => {
    if (!trayTop || !trayBottom || !avatar) return;
    setDetail(null);
    setRenderOpen(true);
    requestRender(trayTop.id, trayBottom.id, trayJacket?.id ?? null);
  };

  const setCategory = (slot: number, index: number) => {
    if (!isMobile && cats[(slot + 1) % 2] === index) return;
    setCats((current) => current.map((value, i) => (i === slot ? index : value)));
    setDetail(null);
  };

  return (
    <main className={`archive-shell${trayFilled ? " has-tray" : ""}`}>
      <aside className="scan-panel" aria-hidden="true">
        <div className="avatar-boundary">
          <span className="avatar-boundary-box">{avatar && <img src={avatar.avatar_url} alt="" />}</span>
        </div>
      </aside>

      <div className="archive-content">
        <header className="mobile-header"><span>FORM / 06</span><span>CLOSET</span></header>
        {itemsQ.isPending && <Loader label="Fetching your closet…" />}
        {itemsQ.isError && (
          <StatePanel title="The closet is out of reach" actions={<button type="button" className="solid-btn" onClick={itemsQ.refetch}>try again</button>}>
            We couldn&apos;t load your garments right now.
          </StatePanel>
        )}
        {itemsQ.items && items.length === 0 && (
          <StatePanel title="Your closet is empty" actions={<Link href="/add-item" className="solid-btn">add your first piece</Link>}>
            Photograph a garment to start building outfits.
          </StatePanel>
        )}
        {itemsQ.items && items.length > 0 && [0, 1].map((slot) => {
          const studyIndex = cats[slot] ?? 0;
          const study = collection[studyIndex];
          if (!study) return null;
          const otherCat = cats[(slot + 1) % 2];
          return (
            <section className={`study-section${slot === 1 ? " study-section--secondary" : ""}`} key={`study-${slot}`} aria-label={`${study.name} study`}>
              <div className="study-topline">
                <span className="study-number" />
                <nav className="category-nav" aria-label={`Navigate collection from ${study.name}`}>
                  {collection.map((category, index) => (
                    <Button key={`nav-${index}`} variant="nav" aria-current={index === studyIndex ? "true" : undefined} disabled={!isMobile && index === otherCat} onClick={() => setCategory(slot, index)} className={index === studyIndex ? "is-current" : ""}>
                      {category.name}
                    </Button>
                  ))}
                </nav>
                <span className="topline-end" />
              </div>
              {study.items.length === 0
                ? <div className="study-empty"><p>No {study.type} yet.</p><Link href="/add-item" className="ghost-btn">add {study.type}</Link></div>
                : <Carousel key={`carousel-${slot}-${studyIndex}-${study.items.length}`} study={study} onOpen={(image) => setDetail(study.items[image] ?? null)} />}
            </section>
          );
        })}
      </div>

      <Link href="/add-item" className="add-fab" aria-label="Add item"><Plus size={18} strokeWidth={1.75} /> add item</Link>

      {detail && (
        <div className="preview-backdrop" role="presentation" onClick={() => setDetail(null)}>
          <div className="detail-panel" role="dialog" aria-modal="true" aria-label="Item detail" onClick={(event) => event.stopPropagation()}>
            <Button variant="close" aria-label="Close" className="detail-close" onClick={() => setDetail(null)}><X size={20} strokeWidth={1.5} /></Button>
            <img src={detail.cutout_url} alt={detail.retailer_item_name ?? detail.garment_type} />
            <div className="detail-info">
              <p className="detail-kicker">{detail.category} · {detail.garment_type}</p>
              <h2>{detail.retailer_item_name ?? "Untitled piece"}</h2>
              <div className="color-compare">
                <SwatchChip color={detail.primary_color} label="extracted" />
                {detail.secondary_color && <SwatchChip color={detail.secondary_color} label="secondary" />}
              </div>
              {tray[SLOT_OF[detail.category]] === detail.id ? (
                <div className="tray-added">
                  <span className="solid-btn" aria-disabled="true">added to outfit</span>
                  <button type="button" className="ghost-btn" onClick={() => { const next = { ...tray }; delete next[SLOT_OF[detail.category]]; updateTray(next); }}>remove</button>
                </div>
              ) : (
                <button type="button" className="solid-btn" onClick={() => updateTray({ ...tray, [SLOT_OF[detail.category]]: detail.id })}>add to outfit</button>
              )}
            </div>
          </div>
        </div>
      )}
      {trayFilled && (
        <div className="outfit-tray" role="region" aria-label="Outfit">
          {SLOTS.map((slot) => {
            const it = trayItem(slot);
            return (
              <div className="tray-slot" key={slot}>
                {it ? <img src={it.cutout_url} alt={it.retailer_item_name ?? slot} /> : <span className="tray-empty">{slot}{slot === "jacket" ? " (optional)" : ""}</span>}
                {it && <button type="button" className="tray-clear" aria-label={`Clear ${slot}`} onClick={() => { const next = { ...tray }; delete next[slot]; updateTray(next); }}><X size={12} strokeWidth={2} /></button>}
              </div>
            );
          })}
          <div className="tray-action">
            {avatar === null ? (
              <Link href="/scan" className="solid-btn">scan yourself first</Link>
            ) : (
              <button type="button" className="solid-btn" onClick={seeItOnMe} disabled={!canRender || !avatar}>see it on me</button>
            )}
            {!canRender && <small className="tray-hint">{!trayTop && !trayBottom ? "add a top and a bottom" : !trayTop ? "add a top" : "add a bottom"}</small>}
          </div>
        </div>
      )}

      {renderOpen && avatar && (
        <div className="preview-backdrop" role="presentation" onClick={closeRender}>
          <div className="render-panel" role="dialog" aria-modal="true" aria-label="Your outfit" onClick={(event) => event.stopPropagation()}>
            <Button variant="close" aria-label="Close" className="detail-close" onClick={closeRender}><X size={20} strokeWidth={1.5} /></Button>
            {(() => {
              const shown = view?.generated ?? view?.local ?? (loading ? avatar.wireframe_url : avatar.avatar_url);
              return (
                <div className={`stylist-avatar-box${view?.pending || loading ? " render-frame--pending" : ""}`}>
                  <img key={shown} className={`render-img${view?.generated && shown === view.generated ? " render-img--generated" : ""}`} src={shown} alt="Your avatar wearing this outfit" />
                </div>
              );
            })()}
            <p className="render-status" aria-live="polite">{view?.pending || loading ? "styling…" : " "}</p>
          </div>
        </div>
      )}
    </main>
  );
}
