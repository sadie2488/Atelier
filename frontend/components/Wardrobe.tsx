"use client";

import { useRef, useState, type CSSProperties } from "react";
import s from "./Wardrobe.module.css";

/** A white armoire: doors swing open on hover (onto a see-through back wall), and a click
 *  zooms the view through the open interior before calling onEnter. Pure CSS/SVG. */
export function Wardrobe({ onEnter, label = "click me to enter", room = "oak" }: { onEnter: () => void; label?: string; room?: "oak" | "walnut" | "slate" | "dim" | "dim-light" | "dim-dark" | "dim-darker" | "dim-black" }) {
  const rootRef = useRef<HTMLButtonElement>(null);
  const openingRef = useRef<HTMLSpanElement>(null);
  const [zoom, setZoom] = useState<CSSProperties | null>(null);

  function enter() {
    if (zoom) return;
    const root = rootRef.current, opening = openingRef.current;
    if (!root || !opening) { onEnter(); return; }
    const r = root.getBoundingClientRect(), o = opening.getBoundingClientRect();
    const cx = o.left + o.width / 2, cy = o.top + o.height / 2;
    const scale = Math.max(window.innerWidth / o.width, window.innerHeight / o.height) * 1.6;
    setZoom({
      transformOrigin: `${cx - r.left}px ${cy - r.top}px`,
      ["--wd-zoom" as string]: `translate(${window.innerWidth / 2 - cx}px, ${window.innerHeight / 2 - cy}px) scale(${scale})`,
    });
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.setTimeout(onEnter, reduced ? 0 : 1250);
  }

  return (
    <div className={`${s.scene} ${zoom ? s.entering : ""}`} data-room={room}>
      <div className={s.room} aria-hidden>
        <span className={s.wall} /><span className={s.pictureRail} /><span className={s.ground}><span className={s.planks} /></span><span className={s.groundShade} /><span className={s.baseboard} />
      </div>
      <div className={s.stand}>
      <button ref={rootRef} type="button" className={s.wardrobe} style={zoom ?? undefined} onClick={enter} aria-label={label}>
        <span className={s.crown} aria-hidden>
          <span className={s.cap} /><span className={s.cove} /><span className={s.fillet} />
        </span>
        <span className={s.body}>
          <span ref={openingRef} className={s.opening}>
            <svg className={s.hangers} viewBox="0 0 200 120" preserveAspectRatio="xMidYMin meet" aria-hidden>
              <defs>
                <linearGradient id="wd-rail" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="#f4f4f2" /><stop offset=".5" stopColor="#b9bcc0" /><stop offset="1" stopColor="#8e9296" />
                </linearGradient>
              </defs>
              <rect x="0" y="10" width="200" height="2.2" rx="1.1" fill="url(#wd-rail)" />
              {[52, 100, 148].map((x, i) => (
                <g key={x} transform={`translate(${x} 11)`}><g className={s.hanger} style={{ animationDelay: `${i * 0.18}s` }}>
                  <path d="M0 1.2 c0 -3.4 4.4 -3.4 4.4 0 c0 2.6 -4.4 3.2 -4.4 6.4 L-21 22 Q-23 24 -19.8 24 L19.8 24 Q23 24 21 22 L0 7.6" fill="none" strokeWidth="1" strokeLinejoin="round" strokeLinecap="round" />
                </g></g>
              ))}
            </svg>
            <span className={`${s.door} ${s.left}`}>
              <span className={s.front}><span className={s.panelTop} /><span className={s.panelLow} /><span className={s.knob} /></span>
              <span className={s.back} />
            </span>
            <span className={`${s.door} ${s.right}`}>
              <span className={s.front}><span className={s.panelTop} /><span className={s.panelLow} /><span className={s.knob} /></span>
              <span className={s.back} />
            </span>
          </span>
        </span>
        <span className={s.plinth} aria-hidden />
        <span className={s.legs} aria-hidden><span /><span /></span>
        <span className={s.floor} aria-hidden />
      </button>
      <p className={s.caption} aria-hidden>{label}</p>
      </div>
    </div>
  );
}
