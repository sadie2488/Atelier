"use client";

import type { Category } from "@/lib/api";

// Per-category stylist defaults set from the closet (one item id per category), kept in this browser only.
export type StylistDefaults = Partial<Record<Category, string>>;

const KEY = "atelier:stylist-defaults";

export function getStylistDefaults(): StylistDefaults {
  try {
    const raw = localStorage.getItem(KEY);
    const v: unknown = raw ? JSON.parse(raw) : {};
    if (!v || typeof v !== "object") return {};
    const out: StylistDefaults = {};
    for (const c of ["tops", "bottoms", "jackets"] as const) {
      const id = (v as Record<string, unknown>)[c];
      if (typeof id === "string" && id) out[c] = id;
    }
    return out;
  } catch { return {}; }
}

function write(d: StylistDefaults) {
  try { localStorage.setItem(KEY, JSON.stringify(d)); } catch { /* storage unavailable */ }
}

// Replaces any previous default in that category.
export function setStylistDefault(category: Category, id: string) {
  write({ ...getStylistDefaults(), [category]: id });
}

export function clearStylistDefault(category: Category) {
  const d = getStylistDefaults();
  delete d[category];
  write(d);
}
