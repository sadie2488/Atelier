"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { Button } from "@/components/Button";
import { setDemoOn } from "@/lib/api";
import { useDemoToggle } from "@/lib/hooks";

const links = [
  { label: "Closet", to: "/closet" },
  { label: "Stylist", to: "/stylist" },
  { label: "Scan", to: "/scan" },
] as const;

const pageNames: Record<string, string> = { "/closet": "Closet", "/stylist": "Stylist", "/scan": "Scan", "/insights": "Palette", "/add-item": "Add item" };

export function HangerMenu() {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const demo = useDemoToggle();
  const router = useRouter();
  const closeTimer = useRef<number | null>(null);
  const pressTimer = useRef<number | null>(null);
  const longPressed = useRef(false);

  // Mouse: hover opens; stays open over the icon or the menu; closes ~150 ms after leaving both.
  const cancelClose = () => { if (closeTimer.current) { window.clearTimeout(closeTimer.current); closeTimer.current = null; } };
  const onEnter = (e: RPointerEvent) => { if (e.pointerType !== "mouse") return; cancelClose(); setOpen(true); };
  const onLeave = (e: RPointerEvent) => {
    if (e.pointerType !== "mouse") return;
    cancelClose();
    closeTimer.current = window.setTimeout(() => setOpen(false), 150);
  };
  // Touch: a tap goes home; a long press (~450 ms) opens the menu instead.
  const onTriggerDown = (e: RPointerEvent) => {
    longPressed.current = false;
    if (e.pointerType === "mouse") return;
    pressTimer.current = window.setTimeout(() => { longPressed.current = true; setOpen(true); }, 450);
  };
  const clearPress = () => { if (pressTimer.current) { window.clearTimeout(pressTimer.current); pressTimer.current = null; } };
  const onTriggerClick = () => {
    clearPress();
    if (longPressed.current) { longPressed.current = false; return; }
    setOpen(false);
    router.push("/");
  };
  useEffect(() => () => { cancelClose(); clearPress(); }, []);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (pathname === "/") return null;

  return (
    <div className="hanger-menu" ref={menuRef} onPointerEnter={onEnter} onPointerLeave={onLeave}>
      <Button variant="icon" className="hanger-trigger" aria-label="Home (hover or long-press for menu)" aria-haspopup="true" aria-expanded={open} aria-controls="hanger-dropdown"
        onClick={onTriggerClick} onPointerDown={onTriggerDown} onPointerUp={clearPress} onPointerCancel={clearPress}
        onContextMenu={(e) => e.preventDefault()} onKeyDown={(e) => { if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); } }}>
        <svg viewBox="0 0 48 42" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M19.5 10a4.5 4.5 0 1 1 7.5 3.35c-1.9 1.64-3 2.45-3 4.65v2.3" />
          <path d="M23.9 20.2 4.4 32.6a2.4 2.4 0 0 0 1.3 4.4h36.6a2.4 2.4 0 0 0 1.3-4.4L24.1 20.2" />
        </svg>
      </Button>
      {pageNames[pathname] && <span className="hanger-page">{pageNames[pathname]}</span>}
      {open && (
        <nav id="hanger-dropdown" className="hanger-dropdown" aria-label="Main menu">
          {links.map(({ label, to }) => (
            <Link key={to} href={to} onClick={() => setOpen(false)} aria-current={pathname === to ? "page" : undefined} className={`hanger-link${pathname === to ? " hanger-link--current" : ""}`}>
              {label}
            </Link>
          ))}
          <div className="hanger-demo">
            <button type="button" role="switch" aria-checked={demo.on} disabled={!demo.available} className={`hanger-switch${demo.on ? " is-on" : ""}`} onClick={() => setDemoOn(!demo.on)}>
              <span>demo avatar</span><span className="hanger-switch-track" aria-hidden="true"><span className="hanger-switch-knob" /></span>
            </button>
            {!demo.available && <small>demo avatar not set yet</small>}
            {demo.failed && <small>demo avatar unavailable</small>}
          </div>
        </nav>
      )}
    </div>
  );
}
