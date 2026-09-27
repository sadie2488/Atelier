"use client";

import { useCallback, useEffect, useState } from "react";
import { DEMO_AVATAR_ID, DEMO_EVENT, fetchAvatarNoStore, getDemoOn, getStoredAvatar, listItems, type Item, type StoredAvatar } from "./api";

// Demo avatar fetch failed: the scanned avatar is shown and the menu toggle says so (no silent fallback).
const DEMO_FAIL_EVENT = "atelier:demo-avatar-failed";
let demoFailed = false;
const setDemoFailed = (v: boolean) => { if (demoFailed !== v) { demoFailed = v; window.dispatchEvent(new Event(DEMO_FAIL_EVENT)); } };

// undefined = not read yet (SSR / first paint), null = none stored.
export function useStoredAvatar(): StoredAvatar | null | undefined {
  const [avatar, setAvatar] = useState<StoredAvatar | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    // Demo toggle ON -> the demo avatar (fetched, not stored); OFF -> the scanned one.
    const sync = () => {
      if (getDemoOn() && DEMO_AVATAR_ID) {
        fetchAvatarNoStore(DEMO_AVATAR_ID)
          .then((a) => { setDemoFailed(false); if (alive) setAvatar(a); })
          .catch(() => { setDemoFailed(true); if (alive) setAvatar(getStoredAvatar()); });
      } else { setDemoFailed(false); setAvatar(getStoredAvatar()); }
    };
    sync();
    window.addEventListener(DEMO_EVENT, sync);
    return () => { alive = false; window.removeEventListener(DEMO_EVENT, sync); };
  }, []);
  return avatar;
}

export function useDemoToggle() {
  const [on, setOn] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const sync = () => { setOn(getDemoOn()); setFailed(demoFailed); };
    sync();
    window.addEventListener(DEMO_EVENT, sync);
    window.addEventListener(DEMO_FAIL_EVENT, sync);
    return () => { window.removeEventListener(DEMO_EVENT, sync); window.removeEventListener(DEMO_FAIL_EVENT, sync); };
  }, []);
  return { on, available: !!DEMO_AVATAR_ID, failed: on && failed };
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
