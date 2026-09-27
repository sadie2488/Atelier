"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/Button";

const links = [
  { label: "Home", to: "/" },
  { label: "Closet", to: "/closet" },
  { label: "Stylist", to: "/stylist" },
  { label: "Add item", to: "/add-item" },
  { label: "Scan", to: "/scan" },
] as const;

export function HangerMenu() {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

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
    <div className="hanger-menu" ref={menuRef}>
      <Button variant="icon" className="hanger-trigger" aria-label="Open menu" aria-expanded={open} aria-controls="hanger-dropdown" onClick={() => setOpen((current) => !current)}>
        <svg viewBox="0 0 48 42" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M19.5 10a4.5 4.5 0 1 1 7.5 3.35c-1.9 1.64-3 2.45-3 4.65v2.3" />
          <path d="M23.9 20.2 4.4 32.6a2.4 2.4 0 0 0 1.3 4.4h36.6a2.4 2.4 0 0 0 1.3-4.4L24.1 20.2" />
        </svg>
      </Button>
      {open && (
        <nav id="hanger-dropdown" className="hanger-dropdown" aria-label="Main menu">
          {links.map(({ label, to }) => (
            <Link key={to} href={to} onClick={() => setOpen(false)} aria-current={pathname === to ? "page" : undefined} className={`hanger-link${pathname === to ? " hanger-link--current" : ""}`}>
              {label}
            </Link>
          ))}
        </nav>
      )}
    </div>
  );
}
