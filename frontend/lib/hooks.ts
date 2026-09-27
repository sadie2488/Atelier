"use client";

import { useCallback, useEffect, useState } from "react";
import { getStoredAvatar, listItems, type Item, type StoredAvatar } from "./api";

// undefined = not read yet (SSR / first paint), null = none stored.
export function useStoredAvatar(): StoredAvatar | null | undefined {
  const [avatar, setAvatar] = useState<StoredAvatar | null | undefined>(undefined);
  useEffect(() => { setAvatar(getStoredAvatar()); }, []);
  return avatar;
}

export function useItems() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState(false);
  const load = useCallback(() => {
    setError(false);
    listItems().then(setItems).catch(() => setError(true));
  }, []);
  useEffect(() => { load(); }, [load]);
  return { items, isPending: items === null && !error, isError: error, refetch: load };
}

export function useIsMobile(breakpoint = 768) {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${breakpoint - 1}px)`);
    const on = () => setMobile(mql.matches);
    on();
    mql.addEventListener("change", on);
    return () => mql.removeEventListener("change", on);
  }, [breakpoint]);
  return mobile;
}
