"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/Button";
import { Plus, X } from "@/components/icons";
import { Carousel, type Study } from "@/components/closet/Carousel";
import { Loader, StatePanel } from "@/components/StatePanel";
import { CATEGORIES, type ExtractedColor, type Item } from "@/lib/api";
import { useIsMobile, useItems, useStoredAvatar } from "@/lib/hooks";

type ClosetStudy = Study & { items: Item[]; type: string };

function SwatchChip({ color, label }: { color: ExtractedColor; label: string }) {
  return (
    <div className="swatch">
      <span className="swatch-color" style={{ background: color.hex }} />
      <span><small>{label}</small>{color.name}{color.is_neutral ? <em className="neutral-tag">neutral</em> : color.everyday_neutral ? <em className="neutral-tag">everyday neutral</em> : null}</span>
    </div>
  );
}

export default function ClosetPage() {
  const isMobile = useIsMobile();
  const itemsQ = useItems();
  const avatar = useStoredAvatar();
  const [cats, setCats] = useState([0, 1]);
  const [detail, setDetail] = useState<Item | null>(null);

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
                <div className="swatch"><span className="swatch-color swatch-color--text">Aa</span><span><small>retailer says</small>{detail.retailer_color ?? "—"}</span></div>
              </div>
              {detail.secondary_color && <SwatchChip color={detail.secondary_color} label="secondary" />}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
