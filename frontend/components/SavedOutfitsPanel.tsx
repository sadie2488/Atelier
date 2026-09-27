"use client";

import { useEffect } from "react";
import { X } from "@/components/icons";
import type { Item } from "@/lib/api";
import type { SavedOutfit } from "@/lib/savedOutfits";

const name = (g: Item | undefined, fallback: string) => g?.retailer_item_name || (g ? fallback : `${fallback} (removed)`);

// Drawer listing saved outfits. Choosing one never starts a render; the page shows the saved image.
export function SavedOutfitsPanel({ outfits, byId, onPick, onRemove, onClose }: {
  outfits: SavedOutfit[];
  byId: Map<string, Item>;
  onPick: (o: SavedOutfit) => void;
  onRemove: (o: SavedOutfit) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="saved-backdrop" onClick={onClose}>
      <aside className="saved-drawer" role="dialog" aria-modal="true" aria-label="Saved outfits" onClick={(e) => e.stopPropagation()}>
        <header className="saved-head">
          <h2>saved outfits</h2>
          <button type="button" className="saved-close" aria-label="Close saved outfits" onClick={onClose}><X size={18} /></button>
        </header>
        {outfits.length === 0 ? (
          <p className="saved-empty">No saved outfits yet.</p>
        ) : (
          <ul className="saved-list">
            {outfits.map((o) => {
              const top = byId.get(o.top_id), bottom = byId.get(o.bottom_id), jacket = o.jacket_id ? byId.get(o.jacket_id) : undefined;
              const pieces = [top, bottom, jacket].filter((g): g is Item => !!g);
              const key = `${o.top_id}|${o.bottom_id}|${o.jacket_id ?? ""}`;
              return (
                <li key={key} className="saved-card">
                  <button type="button" className="saved-pick" onClick={() => onPick(o)} aria-label="Wear this saved outfit">
                    <span className="saved-thumb">
                      {o.image_url ? <img src={o.image_url} alt="" /> : pieces.map((g) => <img key={g.id} src={g.cutout_url} alt="" className="saved-cut" />)}
                    </span>
                    <span className="saved-names">
                      <span>{name(top, "top")}</span>
                      <span>{name(bottom, "bottom")}</span>
                      {o.jacket_id ? <span>{name(jacket, "jacket")}</span> : <span className="saved-muted">no jacket</span>}
                    </span>
                  </button>
                  <button type="button" className="saved-remove" aria-label="Remove saved outfit" onClick={() => onRemove(o)}><X size={14} /></button>
                </li>
              );
            })}
          </ul>
        )}
      </aside>
    </div>
  );
}
