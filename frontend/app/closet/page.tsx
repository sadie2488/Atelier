"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/Button";
import { Plus, X } from "@/components/icons";
import { Carousel, type Study } from "@/components/closet/Carousel";
import { Loader, StatePanel } from "@/components/StatePanel";
import { ApiError, CATEGORIES, renameItem, type Category, type ExtractedColor, type Item } from "@/lib/api";
import { useIsMobile, useItems, useStoredAvatar } from "@/lib/hooks";
import { clearStylistDefault, getStylistDefaults, setStylistDefault } from "@/lib/stylistDefaults";

type ClosetStudy = Study & { items: Item[]; type: Category };
type Slot = "top" | "bottom" | "jacket";

// Dresses are tops, so category alone decides the slot (and the `top-N` label).
const SLOT_OF: Record<Category, Slot> = { tops: "top", bottoms: "bottom", jackets: "jacket" };
// The closet no longer builds an outfit tray; clear any stale one so it can't reorder the stylist.
const TRAY_KEY = "atelier:outfit-tray";

function SwatchChip({ color, label }: { color: ExtractedColor; label: string }) {
  return (
    <div className="swatch">
      <span className="swatch-color" style={{ background: color.hex }} />
      <span><small>{label}</small>{color.display_name ?? color.name}{color.is_neutral ? <em className="neutral-tag">neutral</em> : color.everyday_neutral ? <em className="neutral-tag">everyday neutral</em> : null}</span>
    </div>
  );
}

const ATTRIBUTE_LABELS: [string, string][] = [
  ["subcategory", "Type"], ["sleeve", "Sleeve"], ["neckline", "Neckline"], ["material", "Material"], ["fit", "Fit"],
  ["length", "Length"], ["pattern", "Pattern"], ["closure", "Closure"], ["formality", "Formality"],
];

function AttributeList({ attributes }: { attributes?: Item["attributes"] }) {
  const rows = ATTRIBUTE_LABELS.flatMap(([key, label]) => {
    const value = attributes?.[key];
    return typeof value === "string" && value.trim() ? [{ key, label, value: value.trim() }] : [];
  });
  if (!rows.length) return null;
  return (
    <dl className="detail-attributes">
      {rows.map((row) => (
        <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>
      ))}
    </dl>
  );
}

const Pencil = () => (
  <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M17 3a2.85 2.85 0 0 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /><path d="m15 5 4 4" />
  </svg>
);
const Check = () => (
  <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
);

const PlusIcon = () => (
  <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
);

// Plus beside the pencil: makes this garment the stylist's default (shown first) for its category. One per category.
function DefaultToggle({ item }: { item: Item }) {
  const [isDefault, setIsDefault] = useState(() => getStylistDefaults()[item.category] === item.id);
  const [flash, setFlash] = useState(false);
  useEffect(() => {
    if (!flash) return;
    const t = window.setTimeout(() => setFlash(false), 1600);
    return () => window.clearTimeout(t);
  }, [flash]);
  const toggle = () => {
    if (isDefault) { clearStylistDefault(item.category); setIsDefault(false); setFlash(false); }
    else { setStylistDefault(item.category, item.id); setIsDefault(true); setFlash(true); }
  };
  const label = isDefault ? "Default in stylist (press to remove)" : "Set as stylist default";
  return (
    <>
      <button type="button" className={`rename-btn default-btn${isDefault ? " is-default" : ""}`} aria-pressed={isDefault} aria-label={label} title={label} onClick={toggle}>
        {isDefault ? <Check /> : <PlusIcon />}
      </button>
      {flash && <span className="default-flash" role="status">Shown first in the stylist</span>}
    </>
  );
}

// Inline rename: pencil on the left of the name; Enter/check saves, Esc/X cancels. The item id never changes.
function DetailName({ item, onRenamed }: { item: Item; onRenamed: (updated: Item) => void }) {
  const current = item.retailer_item_name ?? "";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(current);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trimmed = draft.trim();

  const start = () => { setDraft(current); setError(null); setEditing(true); };
  const cancel = () => { setEditing(false); setError(null); };
  const save = async () => {
    if (!trimmed || saving) return;
    if (trimmed === current) { setEditing(false); return; }
    setSaving(true); setError(null);
    try { onRenamed(await renameItem(item.id, trimmed)); setEditing(false); }
    catch (e) { setError(e instanceof ApiError && e.code !== "internal_error" ? e.message : "Couldn't rename this piece. The old name is kept."); }
    finally { setSaving(false); }
  };

  if (!editing) {
    return (
      <div className="detail-name">
        <button type="button" className="rename-btn" aria-label="Rename" onClick={start}><Pencil /></button>
        <DefaultToggle key={item.id} item={item} />
        <h2>{item.retailer_item_name ?? "Untitled piece"}</h2>
      </div>
    );
  }
  return (
    <div>
      <form className="rename-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <input className="rename-input" aria-label="Garment name" value={draft} maxLength={80} autoFocus disabled={saving}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); cancel(); } }} />
        <button type="submit" className="rename-btn" aria-label="Save name" disabled={!trimmed || saving}><Check /></button>
        <button type="button" className="rename-btn" aria-label="Cancel rename" onClick={cancel} disabled={saving}><X size={16} strokeWidth={1.8} /></button>
      </form>
      {error && <p className="rename-error" role="status">{error}</p>}
    </div>
  );
}

export default function ClosetPage() {
  const isMobile = useIsMobile();
  const itemsQ = useItems();
  const avatar = useStoredAvatar();
  const [cats, setCats] = useState([0, 1]);
  const [detail, setDetail] = useState<Item | null>(null);

  useEffect(() => { try { sessionStorage.removeItem(TRAY_KEY); } catch { /* storage unavailable */ } }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") setDetail(null); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // The server's order is authoritative (newest first); never re-sort here.
  const items = itemsQ.items ?? [];
  const collection: ClosetStudy[] = CATEGORIES.map((c, i) => {
    const inCategory = items.filter((g) => g.category === c);
    return { name: c.toUpperCase(), title: "", images: inCategory.map((g) => g.cutout_url), index: `0${i + 1}`, type: c, items: inCategory };
  });

  const setCategory = (slot: number, index: number) => {
    if (!isMobile && cats[(slot + 1) % 2] === index) return;
    setCats((current) => current.map((value, i) => (i === slot ? index : value)));
    setDetail(null);
  };

  return (
    <main className="archive-shell">
      <aside className="scan-panel" aria-hidden="true">
        <div className="avatar-boundary">
          <span className="avatar-boundary-box">{avatar && <img src={avatar.avatar_url} alt="" />}</span>
        </div>
      </aside>

      <div className="archive-content">
        <header className="mobile-header"><span>ATELIER</span><span>CLOSET</span></header>
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
                : <Carousel key={`carousel-${slot}-${studyIndex}-${study.items.length}`} study={study} captionPrefix={SLOT_OF[study.type]} onOpen={(image) => setDetail(study.items[image] ?? null)} />}
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
              <DetailName key={detail.id} item={detail} onRenamed={(updated) => { setDetail(updated); itemsQ.refetch(); }} />
              <AttributeList attributes={detail.attributes} />
              <div className="color-compare">
                <SwatchChip color={detail.primary_color} label="extracted" />
                {detail.secondary_color && <SwatchChip color={detail.secondary_color} label="secondary" />}
              </div>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
