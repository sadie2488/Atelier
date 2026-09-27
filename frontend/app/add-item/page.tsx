"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { analyzeItem, ApiError, CATEGORIES, downscale, GARMENT_TYPES, rejectItem, saveItem, type Candidate, type Category, type GarmentType } from "@/lib/api";
import { Loader, StatePanel } from "@/components/StatePanel";

type Step =
  | { s: "capture" }
  | { s: "categorize" }
  | { s: "analyzing" }
  | { s: "pick"; handle: string; candidates: Candidate[]; choice: number | null; saving: boolean }
  | { s: "saved" }
  | { s: "error"; code: string };

const ERRORS: Record<string, { title: string; body: string; action: "rescan" | "retry" | "reshoot" }> = {
  handle_expired: { title: "This scan timed out", body: "The garment scan expired before it was saved. Rescan the piece to continue.", action: "rescan" },
  invalid_request: { title: "Something didn't add up", body: "We couldn't process that request. Check the category and type, then try again.", action: "retry" },
  unsupported_image: { title: "We can't use this photo", body: "The image format or content isn't usable. Shoot the garment flat or on a hanger, in good light, filling the frame.", action: "reshoot" },
  analyze_failed: { title: "Analysis didn't finish", body: "We couldn't analyze this garment just now. Give it another go.", action: "retry" },
  network: { title: "We couldn't reach the atelier", body: "Check your connection and try again.", action: "retry" },
};

export default function AddItemPage() {
  const [step, setStep] = useState<Step>({ s: "capture" });
  const [category, setCategory] = useState<Category>("tops");
  const [type, setType] = useState<GarmentType>("shirt");
  const [color, setColor] = useState("");
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const photo = useRef<Blob | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const camRef = useRef<HTMLInputElement>(null);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  const errorStep = (e: unknown, fallback: string): Step => ({ s: "error", code: e instanceof ApiError && e.code in ERRORS ? e.code : fallback });

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) return setStep({ s: "error", code: "unsupported_image" });
    try {
      const blob = await downscale(file);
      photo.current = blob;
      setPreview(URL.createObjectURL(blob));
      setStep({ s: "categorize" });
    } catch { setStep({ s: "error", code: "unsupported_image" }); }
  };

  const analyze = async () => {
    if (!photo.current) return setStep({ s: "capture" });
    setStep({ s: "analyzing" });
    try {
      const r = await analyzeItem({ image: photo.current, category, garment_type: type, color: color.trim() || undefined, item_name: name.trim() || undefined });
      setStep({ s: "pick", handle: r.temp_handle, candidates: r.candidates, choice: 1, saving: false });
    } catch (e) { setStep(errorStep(e, "analyze_failed")); }
  };

  const save = async () => {
    if (step.s !== "pick" || step.choice === null) return;
    setStep({ ...step, saving: true });
    try { await saveItem(step.handle, step.choice); setStep({ s: "saved" }); }
    catch (e) { setStep(errorStep(e, "invalid_request")); }
  };

  // "None of these": tell the backend, then restart from a fresh photo.
  const rejectAll = async () => {
    if (step.s === "pick") await rejectItem(step.handle).catch(() => {});
    setStep({ s: "capture" });
  };

  const reshoot = () => setStep({ s: "capture" });

  return (
    <main className="flow-page" aria-label="Add item">
      {step.s === "capture" && (
        <StatePanel title="Add a piece" actions={<>
          <button type="button" className="solid-btn" onClick={() => camRef.current?.click()}>take photo</button>
          <button type="button" className="ghost-btn" onClick={() => fileRef.current?.click()}>upload</button>
        </>}>Photograph the garment on its own, flat or on a hanger.</StatePanel>
      )}
      <input ref={camRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = ""; }} />
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = ""; }} />

      {step.s === "categorize" && (
        <form className="item-form" onSubmit={(e) => { e.preventDefault(); void analyze(); }}>
          {preview && <img src={preview} alt="Garment preview" className="item-thumb" />}
          <div className="item-fields">
            <fieldset><legend>category</legend>
              <div className="chip-row">{CATEGORIES.map((c) => (
                <button type="button" key={c} className={`chip${c === category ? " is-on" : ""}`} onClick={() => { setCategory(c); setType(GARMENT_TYPES[c][0]!); }}>{c}</button>
              ))}</div>
            </fieldset>
            <fieldset><legend>type</legend>
              <div className="chip-row">{GARMENT_TYPES[category].map((t) => (
                <button type="button" key={t} className={`chip${t === type ? " is-on" : ""}`} onClick={() => setType(t)}>{t}</button>
              ))}</div>
            </fieldset>
            <label>retailer color <span>(optional)</span><input value={color} onChange={(e) => setColor(e.target.value)} maxLength={40} placeholder="e.g. Oatmeal" /></label>
            <label>item name <span>(optional)</span><input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="e.g. Linen camp shirt" /></label>
            <div className="state-actions"><button type="submit" className="solid-btn">analyze</button><button type="button" className="ghost-btn" onClick={reshoot}>reshoot</button></div>
          </div>
        </form>
      )}

      {step.s === "analyzing" && <div className="flow-center"><div className="shimmer-card" /><Loader label="Analyzing fabric, color and outline…" /></div>}

      {step.s === "pick" && (
        <div className="cutout-pick">
          <h2 className="state-title">Choose a cutout</h2>
          <div className="cutout-row">{step.candidates.map((c) => (
            <button type="button" key={c.index} className={`cutout cutout--${c.variant}${step.choice === c.index ? " is-on" : ""}`} onClick={() => setStep({ ...step, choice: c.index })} aria-pressed={step.choice === c.index}>
              <span className="cutout-img"><img src={c.cutout_url} alt={`${c.variant} cutout`} /></span>
              <span>{c.variant}</span>
            </button>
          ))}</div>
          <div className="state-actions">
            <button type="button" className="solid-btn" disabled={step.choice === null || step.saving} onClick={save}>{step.saving ? "saving…" : "save"}</button>
            <button type="button" className="ghost-btn" disabled={step.saving} onClick={rejectAll}>none of these</button>
          </div>
        </div>
      )}

      {step.s === "saved" && (
        <StatePanel title="Added to your closet" actions={<><Link href="/closet" className="solid-btn">view closet</Link><button type="button" className="ghost-btn" onClick={reshoot}>add another</button></>} />
      )}

      {step.s === "error" && (() => {
        const err = ERRORS[step.code] ?? ERRORS["analyze_failed"]!;
        return (
          <StatePanel title={err.title} actions={<>
            {err.action === "retry" && preview
              ? <button type="button" className="solid-btn" onClick={() => setStep({ s: "categorize" })}>retry</button>
              : <button type="button" className="solid-btn" onClick={reshoot}>{err.action === "rescan" ? "rescan" : "reshoot"}</button>}
            <Link href="/closet" className="ghost-btn">back to closet</Link>
          </>}>{err.body}</StatePanel>
        );
      })()}
    </main>
  );
}
