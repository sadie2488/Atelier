"use client";

import { useCallback, useSyncExternalStore } from "react";

// Outfits saved from the stylist, kept in this browser only (newest first, max 30).
export type SavedOutfit = {
  top_id: string;
  bottom_id: string;
  jacket_id: string | null;
  image_url: string | null; // the Nano Banana try-on shown when saved, if any (relative URL)
  explanation: string | null;
  saved_at: string; // ISO timestamp
  name?: string; // user-given name (older entries have none)
};

const KEY = "atelier:saved-outfits";
const MAX = 30;
const EMPTY: SavedOutfit[] = [];
const listeners = new Set<() => void>();
let cacheRaw: string | null = null;
let cache: SavedOutfit[] = EMPTY;

const sameCombo = (a: Pick<SavedOutfit, "top_id" | "bottom_id" | "jacket_id">, b: Pick<SavedOutfit, "top_id" | "bottom_id" | "jacket_id">) =>
  a.top_id === b.top_id && a.bottom_id === b.bottom_id && (a.jacket_id ?? null) === (b.jacket_id ?? null);

function read(): SavedOutfit[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw === cacheRaw) return cache;
    cacheRaw = raw;
    const v: unknown = raw ? JSON.parse(raw) : [];
    cache = Array.isArray(v) ? (v as SavedOutfit[]).filter((o) => o && typeof o.top_id === "string" && typeof o.bottom_id === "string") : EMPTY;
  } catch { cache = EMPTY; }
  return cache;
}

function write(list: SavedOutfit[]): boolean {
  try { localStorage.setItem(KEY, JSON.stringify(list)); } catch { return false; }
  listeners.forEach((l) => l());
  return true;
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  const onStorage = (e: StorageEvent) => { if (e.key === KEY) l(); };
  window.addEventListener("storage", onStorage);
  return () => { listeners.delete(l); window.removeEventListener("storage", onStorage); };
};

export function useSavedOutfits() {
  const outfits = useSyncExternalStore(subscribe, read, () => EMPTY);
  // Newest first; saving the same top/bottom/jacket again replaces the older entry.
  const save = useCallback((o: Omit<SavedOutfit, "saved_at">) => {
    const entry: SavedOutfit = { ...o, jacket_id: o.jacket_id ?? null, saved_at: new Date().toISOString() };
    return write([entry, ...read().filter((x) => !sameCombo(x, entry))].slice(0, MAX));
  }, []);
  const remove = useCallback((o: SavedOutfit) => { write(read().filter((x) => !sameCombo(x, o))); }, []);
  return { outfits, save, remove };
}
