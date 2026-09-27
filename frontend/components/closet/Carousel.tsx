"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/Button";
import { ChevronLeft, ChevronRight } from "@/components/icons";

export type Study = { name: string; title: string; images: string[]; index: string };

const mod = (n: number, m: number) => ((n % m) + m) % m;

export function Carousel({ study, onOpen }: { study: Study; onOpen: (image: number) => void }) {
  const count = study.images.length;
  const [pos, setPos] = useState(0);
  const posRef = useRef(0);
  const targetRef = useRef(0);
  const velRef = useRef(0);
  const dragRef = useRef<{ x: number; start: number; last: number; t: number; v: number; moved: boolean } | null>(null);
  const rafRef = useRef<number | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const hoverTimer = useRef<number | null>(null);

  const spacing = () => (stageRef.current?.clientWidth ?? 800) * 0.34;

  const animate = () => {
    if (rafRef.current !== null) return;
    const tick = () => {
      if (!dragRef.current) {
        const diff = targetRef.current - posRef.current;
        velRef.current = velRef.current * 0.78 + diff * 0.09;
        posRef.current += velRef.current;
        // pictures sliding left/right push the pendulum too
        const pxPerMs = (velRef.current * spacing()) / 16;
        swing.current.motion = Math.max(-30, Math.min(30, -pxPerMs * 22));
        if (Math.abs(diff) < 0.001 && Math.abs(velRef.current) < 0.001) {
          posRef.current = targetRef.current; velRef.current = 0;
          swing.current.motion = 0;
          setPos(posRef.current); rafRef.current = null; return;
        }
        startSwing();
      }
      setPos(posRef.current);
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
  };

  const step = (direction: number) => { targetRef.current = Math.round(targetRef.current) + direction; animate(); };
  const goTo = (index: number) => {
    const current = Math.round(targetRef.current);
    let delta = mod(index - mod(current, count), count);
    if (delta > count / 2) delta -= count;
    targetRef.current = current + delta; animate();
  };

  // Wheel / trackpad moves the carousel only while the cursor is over a garment image's box;
  // anywhere else the page scrolls normally. Touch drag is handled by the pointer handlers below.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    let acc = 0;
    let lockUntil = 0;
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey) return; // pinch-zoom
      const imgs = stage.querySelectorAll<HTMLElement>(".strip-item .image-frame img");
      const over = Array.from(imgs).some((img) => {
        const r = img.getBoundingClientRect();
        return event.clientX >= r.left && event.clientX <= r.right && event.clientY >= r.top && event.clientY <= r.bottom;
      });
      if (!over) return;
      event.preventDefault();
      const d = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
      const px = event.deltaMode === 1 ? d * 16 : event.deltaMode === 2 ? d * 400 : d;
      const now = event.timeStamp;
      if (now < lockUntil) return; // swallow trackpad inertia right after a step
      acc += px;
      if (Math.abs(acc) >= 40) { stage.querySelector<HTMLButtonElement>(acc > 0 ? ".edge-zone--right .carousel-arrow" : ".edge-zone--left .carousel-arrow")?.click(); acc = 0; lockUntil = now + 220; }
    };
    stage.addEventListener("wheel", onWheel, { passive: false });
    return () => stage.removeEventListener("wheel", onWheel);
  }, []);

  useEffect(() => () => {
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    if (hoverTimer.current !== null) window.clearInterval(hoverTimer.current);
  }, []);

  const startHover = (direction: number) => {
    stopHover();
    step(direction);
    hoverTimer.current = window.setInterval(() => step(direction), 400);
  };
  const stopHover = () => { if (hoverTimer.current !== null) { window.clearInterval(hoverTimer.current); hoverTimer.current = null; } };

  // Pendulum: every picture swings from its own top-center pivot
  const swing = useRef({ a: 0, w: 0, target: 0, motion: 0, raf: 0 as number });
  // re-read the live tiles every frame: React swaps these nodes as the row scrolls
  const applySwing = (angle: number) => {
    const nodes = stageRef.current?.querySelectorAll<HTMLElement>(".strip-item");
    if (!nodes) return;
    nodes.forEach((el, i) => {
      // slight per-item variation so the row doesn't swing as one rigid block
      el.style.setProperty("--swing", `${(angle * (0.82 + ((i * 7) % 5) * 0.09)).toFixed(3)}deg`);
    });
  };
  const swingTick = () => {
    const s = swing.current;
    const dragging = !!dragRef.current;
    const drive = dragging ? s.target : s.motion;
    // spring toward the drive angle (lag), then weakly damped pendulum back to 0
    const k = dragging ? 0.06 : 0.05;
    const damp = dragging ? 0.78 : Math.abs(drive) > 0.15 ? 0.86 : 0.93;
    s.w = (s.w + (drive - s.a) * k) * damp;
    s.a = Math.max(-32, Math.min(32, s.a + s.w));
    if (dragging) s.target *= 0.9; // cursor stopped → drift back toward hanging
    applySwing(s.a);
    if (!dragging && Math.abs(drive) < 0.05 && Math.abs(s.a) < 0.02 && Math.abs(s.w) < 0.02) {
      applySwing(0);
      s.a = 0; s.w = 0; s.motion = 0; s.raf = 0; return;
    }
    s.raf = requestAnimationFrame(swingTick);
  };
  const startSwing = () => { if (!swing.current.raf) swing.current.raf = requestAnimationFrame(swingTick); };


  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest(".edge-zone")) return;
    dragRef.current = { x: event.clientX, start: posRef.current, last: event.clientX, t: event.timeStamp, v: 0, moved: false };
    velRef.current = 0;
    applySwing(0);
    applySwing(0);
    swing.current.a = 0; swing.current.w = 0; swing.current.target = 0; swing.current.motion = 0;
  };


  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const dx = event.clientX - drag.x;
    if (Math.abs(dx) > 4 && !drag.moved) { drag.moved = true; event.currentTarget.setPointerCapture(event.pointerId); }
    if (!drag.moved) return;
    const now = event.timeStamp;
    drag.v = (event.clientX - drag.last) / Math.max(1, now - drag.t);
    drag.last = event.clientX; drag.t = now;
    posRef.current = drag.start - dx / spacing();
    swing.current.target = Math.max(-30, Math.min(30, drag.v * 22));
    startSwing();
    animate();
  };
  const onPointerUp = () => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || !drag.moved) return;
    // release impulse scales with flick speed
    swing.current.w += Math.max(-4, Math.min(4, drag.v * 2.2));
    startSwing();
    targetRef.current = Math.round(posRef.current - (drag.v * 260) / spacing());
    velRef.current = 0;
    animate();
  };

  const centerIndex = mod(Math.round(pos), count);
  const base = Math.round(pos);
  const dirRef = useRef(0);
  const [selected, setSelected] = useState<{ index: number; k: number } | null>(null);
  const pickItem = (imageIndex: number, isCenter: boolean) => {
    if (isCenter && selected?.index === imageIndex) { onOpen(imageIndex); return; }
    if (!isCenter) goTo(imageIndex);
    setSelected({ index: imageIndex, k: (selected?.k ?? 0) + 1 });
  };

  const onStageMove = (event: React.MouseEvent<HTMLDivElement>) => {
    if (dragRef.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const fraction = (event.clientX - rect.left) / rect.width;
    const direction = fraction > 0.42 ? 1 : fraction < 0.16 ? -1 : 0;
    if (direction === dirRef.current) return;
    dirRef.current = direction;
    if (direction === 0) stopHover();
    else startHover(direction);
  };
  const onStageLeave = () => { dirRef.current = 0; stopHover(); };
  const label = study.name.trim() || study.title.trim() || `N°${study.index}`;

  const scrub = (event: React.PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    goTo(Math.round(fraction * (count - 1)));
  };

  return (
    <>
      <div className="study-stage" ref={stageRef}
        onMouseMove={onStageMove} onMouseLeave={onStageLeave}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
        <div className="edge-zone edge-zone--left">
          <Button variant="icon" className="carousel-arrow" aria-label="Previous image" onClick={() => step(-1)}><ChevronLeft size={22} strokeWidth={1.25} /></Button>
        </div>
        <div className="image-strip">
          {Array.from({ length: 8 }, (_, i) => base - 2 + i).map((k) => {
            const imageIndex = mod(k, count);
            const image = study.images[imageIndex];
            if (!image) return null;
            const d = k - pos;
            const abs = Math.abs(d);
            const scale = abs <= 1 ? 1 - abs * 0.18 : Math.max(0.55, 0.82 - (abs - 1) * 0.1);
            const isSelected = selected?.index === imageIndex && Math.round(abs) === 0;
            return (
              <Button key={isSelected ? `k-${k}-sel-${selected?.k}` : `k-${k}`} variant="icon" className={`strip-item${isSelected ? " is-selected" : ""}`} aria-label={`Open ${label} image ${imageIndex + 1}`}
                style={{ transform: `translate(-50%, -50%) translateX(${d * 32}cqw) scale(${scale})`, zIndex: isSelected ? 20 : 10 - Math.round(abs) }}
                onClick={() => pickItem(imageIndex, Math.round(abs) === 0)}>
                <span className="image-frame"><img src={image} alt={`${label.toLowerCase()} ${imageIndex + 1}`} width={768} height={1024} draggable={false} loading={abs < 1.5 ? "eager" : "lazy"} /></span>
              </Button>
            );
          })}
        </div>
        <div className="image-caption" key={`caption-${centerIndex}`}>{label}</div>
        <div className="edge-zone edge-zone--right">
          <Button variant="icon" className="carousel-arrow" aria-label="Next image" onClick={() => step(1)}><ChevronRight size={22} strokeWidth={1.25} /></Button>
        </div>
      </div>
      <div className="study-footer">
        <div className="progress-area">
          <span>{`${String(centerIndex + 1).padStart(2, "0")}/${String(count).padStart(2, "0")}`}</span>
          <div className="progress-line" role="slider" aria-label="Image position" aria-valuemin={1} aria-valuemax={count} aria-valuenow={centerIndex + 1}
            onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); scrub(event); }}
            onPointerMove={(event) => { if (event.currentTarget.hasPointerCapture(event.pointerId)) scrub(event); }}>
            <div className="progress-dot" style={{ left: `clamp(4px, ${(mod(pos, count) / Math.max(1, count - 1)) * 100}%, calc(100% - 4px))` }} />
          </div>
        </div>
      </div>
    </>
  );
}
