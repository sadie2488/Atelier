"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Loader, StatePanel } from "@/components/StatePanel";
import { ApiError, getPaletteInsights, type PaletteInsights } from "@/lib/api";
import { useItems } from "@/lib/hooks";

type LoadState =
  | { s: "loading" }
  | { s: "error"; message: string }
  | { s: "ready"; data: PaletteInsights };

export default function InsightsPage() {
  const [state, setState] = useState<LoadState>({ s: "loading" });
  const itemsQ = useItems(); // only used to look up cutout images for the most-versatile items

  const load = useCallback(() => {
    setState({ s: "loading" });
    getPaletteInsights()
      .then((data) => setState({ s: "ready", data }))
      .catch((e) => setState({ s: "error", message: e instanceof ApiError ? e.message : "Something went wrong." }));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (state.s === "loading") return <main className="flow-page"><Loader label="Reading your palette…" /></main>;

  if (state.s === "error") return (
    <main className="flow-page" aria-label="Palette insights">
      <StatePanel title="The palette is out of reach" actions={<button type="button" className="solid-btn" onClick={load}>try again</button>}>
        {state.message}
      </StatePanel>
    </main>
  );

  const data = state.data;

  if (data.item_count === 0) return (
    <main className="flow-page" aria-label="Palette insights">
      <StatePanel title="No colors yet" actions={<Link href="/add-item" className="solid-btn">add your first piece</Link>}>
        Add a few garments and your palette will show up here.
      </StatePanel>
    </main>
  );

  const cutoutFor = (itemId: string) => itemsQ.items?.find((it) => it.id === itemId)?.cutout_url;

  return (
    <main className="flow-page" aria-label="Palette insights">
      <div className="insights-page">
        <h2 className="state-title">Your palette</h2>

        <section className="insights-section">
          <p className="detail-kicker">swatches</p>
          <div className="insights-swatches">
            {data.swatches.map((sw) => (
              <div className="swatch insights-swatch" key={sw.item_id}>
                <span className="swatch-color" style={{ background: sw.hex }} />
                <span>{sw.display_name ?? sw.family}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="insights-section">
          <p className="detail-kicker">color families</p>
          <div className="insights-bars">
            {data.families.map((f) => (
              <div className="insights-bar-row" key={f.family}>
                <span className="insights-bar-label">{f.family.replace(/_/g, " ")}</span>
                <span className="insights-bar-track">
                  <span className="insights-bar-fill" style={{ width: `${Math.round(f.share * 100)}%`, background: f.hex }} />
                </span>
                <span className="insights-bar-pct">{Math.round(f.share * 100)}%</span>
              </div>
            ))}
          </div>
        </section>

        <section className="insights-section">
          <p className="detail-kicker">neutral share</p>
          <p className="insights-neutral">{Math.round(data.neutral_share * 100)}%</p>
        </section>

        {data.insights.length > 0 && (
          <section className="insights-section">
            <p className="detail-kicker">insights</p>
            <ul className="insights-list">
              {data.insights.map((line, i) => <li key={i}>{line}</li>)}
            </ul>
          </section>
        )}

        {data.missing_families.length > 0 && (
          <section className="insights-section">
            <p className="detail-kicker">missing families</p>
            <div className="insights-chip-row">
              {data.missing_families.map((f) => <span className="insights-chip" key={f}>missing: {f.replace(/_/g, " ")}</span>)}
            </div>
          </section>
        )}

        {data.most_versatile.length > 0 && (
          <section className="insights-section">
            <p className="detail-kicker">most versatile</p>
            <div className="insights-versatile-row">
              {data.most_versatile.map((v) => {
                const cutout = cutoutFor(v.item_id);
                return (
                  <div className="insights-versatile-item" key={v.item_id}>
                    {cutout
                      ? <img src={cutout} alt={v.item_id} />
                      : <span className="swatch-color swatch-color--text">{v.item_id.charAt(0).toUpperCase()}</span>}
                    <small>{v.item_id} &middot; {v.outfit_count} outfit{v.outfit_count === 1 ? "" : "s"}</small>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
