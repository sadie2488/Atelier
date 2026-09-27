"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/Button";
import { Plus, X } from "@/components/icons";
import { Carousel, type Study } from "@/components/closet/Carousel";
import { Loader, StatePanel } from "@/components/StatePanel";
import { ApiError, CATEGORIES, updateItem, type Category, type ExtractedColor, type Item } from "@/lib/api";
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
  ["length", "Length"], ["rise", "Rise"], ["pattern", "Pattern"], ["closure", "Closure"], ["formality", "Formality"],
  ["season", "Season"], ["warmth", "Warmth"],
];

// Keys offered for editing per category (plus any other keys the item already has).
const EDIT_KEYS: Record<Category, string[]> = {
  tops: ["subcategory", "sleeve", "neckline", "material", "fit", "pattern", "closure", "formality", "season", "warmth"],
  bottoms: ["subcategory", "material", "length", "rise", "pattern", "closure", "formality", "season", "warmth"],
  jackets: ["subcategory", "material", "length", "pattern", "closure", "formality", "season", "warmth"],
};
const LABEL_OF = Object.fromEntries(ATTRIBUTE_LABELS);
const clean = (v: unknown) => (typeof v === "string" ? v.trim() : "");
const NA = "n/a";
const OTHER = "__other";
// Known options per detail (free text via "other..." is always allowed; every detail also offers n/a).
const OPTIONS: Record<string, string[] | Record<Category, string[]>> = {
  subcategory: {
    tops: ["tank", "cami", "t-shirt", "shirt", "button-up shirt", "blouse", "sweater", "cardigan", "turtleneck", "hoodie", "dress", "slip dress"],
    bottoms: ["jeans", "trousers", "shorts", "skirt", "sweatpants", "leggings"],
    jackets: ["blazer", "coat", "overcoat", "moto jacket", "denim jacket", "utility jacket", "puffer", "cardigan"],
  },
  sleeve: ["sleeveless", "straps", "short sleeve", "3/4 sleeve", "long sleeve"],
  neckline: ["crew neck", "v-neck", "scoop neck", "collar", "turtleneck", "square neck", "off-shoulder"],
  material: ["cotton", "linen", "silk", "satin", "wool", "cashmere", "denim", "leather", "polyester", "knit"],
  fit: ["tight", "regular", "loose"],
  length: { tops: [], bottoms: ["thigh", "knee", "calf", "full"], jackets: ["cropped", "regular", "long"] },
  pattern: ["solid", "striped", "plaid", "floral", "print", "textured"],
  closure: ["none", "buttons", "zip", "snaps"],
  formality: ["casual", "smart", "dressy"],
  rise: ["high", "mid", "low"],
  season: ["spring", "summer", "fall", "winter", "all-season"],
  warmth: ["light", "mid", "heavy"],
};
const optionsFor = (key: string, cat: Category): string[] => {
  const o = OPTIONS[key];
  return !o ? [] : Array.isArray(o) ? o : o[cat] ?? [];
};
const editKeys = (item: Item) => {
  const base = EDIT_KEYS[item.category];
  return ATTRIBUTE_LABELS.map(([k]) => k).filter((k) => base.includes(k) || clean(item.attributes?.[k]));
};
type Pick = { choice: string; other: string };
const initialPick = (value: string, opts: string[]): Pick =>
  !value || value === NA || opts.includes(value) ? { choice: value, other: "" } : { choice: OTHER, other: value };
const pickValue = (p: Pick) => (p.choice === OTHER ? p.other.trim() : p.choice);

function MainColor({ color }: { color: ExtractedColor }) {
  return (
    <div className="detail-color">
      <span className="swatch-color" style={{ background: color.hex }} aria-hidden="true" />
      <span className="detail-color-text"><small>Color</small>{color.display_name ?? color.name} <code>{color.hex}</code></span>
    </div>
  );
}

function AttributeList({ attributes }: { attributes?: Item["attributes"] }) {
  const rows = ATTRIBUTE_LABELS.flatMap(([key, label]) => {
    const value = clean(attributes?.[key]);
    return value ? [{ key, label, value }] : [];
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
      <button type="button" className={`rename-btn media-btn media-btn--bl default-btn${isDefault ? " is-default" : ""}`} aria-pressed={isDefault} aria-label={label} title={label} onClick={toggle}>
        {isDefault ? <Check /> : <PlusIcon />}
      </button>
      {flash && <span className="default-flash" role="status">Shown first in the stylist</span>}
    </>
  );
}

// Detail popup body. The pencil (image top-left) opens one edit mode for the name and every detail;
// save sends the name (if changed) and the changed details in one PATCH. The item id never changes.
function ItemDetail({ item, onSaved }: { item: Item; onSaved: (updated: Item) => void }) {
  const currentName = item.retailer_item_name ?? "";
  const keys = editKeys(item);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(currentName);
  const [picks, setPicks] = useState<Record<string, Pick>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = () => {
    setName(currentName);
    setPicks(Object.fromEntries(keys.map((k) => [k, initialPick(clean(item.attributes?.[k]), optionsFor(k, item.category))])));
    setError(null); setEditing(true);
  };
  const cancel = () => { setEditing(false); setError(null); };
  const save = async () => {
    if (saving) return;
    const patch: { name?: string; attributes?: Record<string, string> } = {};
    const n = name.trim();
    if (n && n !== currentName) patch.name = n;
    const changed: Record<string, string> = {};
    for (const k of keys) {
      const p = picks[k];
      if (!p || (p.choice === OTHER && !p.other.trim())) continue; // empty "other" = unchanged
      const v = pickValue(p);
      if (v !== clean(item.attributes?.[k])) changed[k] = v;
    }
    if (Object.keys(changed).length) patch.attributes = changed;
    if (!patch.name && !patch.attributes) { setEditing(false); return; }
    setSaving(true); setError(null);
    try { onSaved(await updateItem(item.id, patch)); setEditing(false); }
    catch (e) { setError(e instanceof ApiError && e.code !== "internal_error" ? e.message : "Couldn\u2019t save these changes. Nothing was changed."); }
    finally { setSaving(false); }
  };
  const setPick = (k: string, p: Partial<Pick>) => setPicks((cur) => ({ ...cur, [k]: { ...(cur[k] ?? { choice: "", other: "" }), ...p } }));

  return (
    <>
      <div className="detail-media">
        <img src={item.cutout_url} alt={item.retailer_item_name ?? item.garment_type} />
        <button type="button" className="rename-btn media-btn media-btn--tl" aria-label={editing ? "Cancel editing" : "Edit garment"} aria-pressed={editing} title="Edit name and details" onClick={editing ? cancel : start}><Pencil /></button>
        <DefaultToggle key={item.id} item={item} />
      </div>
      <div className="detail-info">
        <p className="detail-kicker">{item.category} · {item.garment_type}</p>
        {!editing ? (
          <>
            <div className="detail-name"><h2>{item.retailer_item_name ?? "Untitled piece"}</h2></div>
            <MainColor color={item.primary_color} />
            <AttributeList attributes={item.attributes} />
          </>
        ) : (
          <form className="attr-block" onSubmit={(e) => { e.preventDefault(); void save(); }}
            onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); cancel(); } }}>
            <input className="rename-input" aria-label="Garment name" value={name} maxLength={80} autoFocus disabled={saving} onChange={(e) => setName(e.target.value)} />
            <div className="detail-attributes attr-form">
              {keys.map((k) => {
                const opts = optionsFor(k, item.category);
                const p = picks[k] ?? { choice: "", other: "" };
                return (
                  <label key={k}><span>{LABEL_OF[k] ?? k}</span>
                    <span className="attr-pick">
                      <select className="attr-input" data-key={k} value={p.choice} disabled={saving} onChange={(e) => setPick(k, { choice: e.target.value })}>
                        <option value="">{"\u2014"}</option>
                        {opts.map((o) => <option key={o} value={o}>{o}</option>)}
                        <option value={NA}>n/a</option>
                        <option value={OTHER}>{"other\u2026"}</option>
                      </select>
                      {p.choice === OTHER && (
                        <input className="attr-input" data-other={k} aria-label={`${LABEL_OF[k] ?? k} (other)`} placeholder="type a value" value={p.other} maxLength={60} disabled={saving}
                          onChange={(e) => setPick(k, { other: e.target.value })} />
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
            <div className="attr-actions">
              <button type="submit" className="attr-edit-btn" disabled={saving || !name.trim()}><Check /> {saving ? "saving\u2026" : "save"}</button>
              <button type="button" className="attr-edit-btn" onClick={cancel} disabled={saving}><X size={16} strokeWidth={1.8} /> cancel</button>
            </div>
            {error && <p className="rename-error" role="status">{error}</p>}
          </form>
        )}
        <div className="color-compare">
          <SwatchChip color={item.primary_color} label="extracted" />
          {item.secondary_color && <SwatchChip color={item.secondary_color} label="secondary" />}
        </div>
      </div>
    </>
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
          <span className="avatar-boundary-box">{avatar && <span className="avatar-floor" aria-hidden="true" />}{avatar && <img src={avatar.avatar_url} alt="" />}</span>
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
            <ItemDetail key={detail.id} item={detail} onSaved={(updated) => { setDetail(updated); itemsQ.refetch(); }} />
          </div>
        </div>
      )}
    </main>
  );
}
