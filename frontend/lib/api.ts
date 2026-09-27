// Typed client for the Atelier backend (coordination/BACKEND_API.md).
// Always relative paths: next.config.ts rewrites /api/* and /media/* to BACKEND_URL.
import type {
  AnalyzeResponse, Avatar, AvatarScanResponse, Category, ErrorCode, ErrorResponse, ExtractedColor,
  GarmentType, HealthResponse, Item, ItemListResponse, Outfit, OutfitsGenerateResponse,
  PaletteInsights, RenameRequest, RenderJob, RenderRequest,
} from "./api-types";

export type { Avatar, Category, ExtractedColor, GarmentType, Item, Outfit, PaletteInsights, RenderJob };
export type Candidate = AnalyzeResponse["candidates"][number];

export const CATEGORIES: Category[] = ["tops", "bottoms", "jackets"];
export const GARMENT_TYPES: Record<Category, GarmentType[]> = {
  tops: ["shirt", "dress"],
  bottoms: ["pants", "skirt", "shorts"],
  jackets: ["jacket", "coat"],
};

export type ApiErrorCode = ErrorCode | "network";
export class ApiError extends Error {
  constructor(public code: ApiErrorCode, message: string) { super(message); }
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try { res = await fetch(`/api${path}`, init); }
  catch { throw new ApiError("network", "We couldn't reach the atelier. Check your connection and try again."); }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (body as ErrorResponse | null)?.error;
    throw new ApiError(err?.code ?? "internal_error", err?.message ?? "Something went wrong.");
  }
  return body as T;
}

const json = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ---------- endpoints ----------
export async function getHealth(): Promise<boolean> {
  try { return (await http<HealthResponse>("/health")).status === "ok"; } catch { return false; }
}

export async function scanAvatar(photo: Blob): Promise<StoredAvatar> {
  const form = new FormData();
  form.append("image", photo, "scan.jpg");
  const a = await http<AvatarScanResponse>("/avatar/scan", { method: "POST", body: form });
  return storeAvatar(a);
}

export async function fetchAvatar(id: string): Promise<StoredAvatar> {
  return storeAvatar(await http<Avatar>(`/avatar/${encodeURIComponent(id)}`));
}

export async function listItems(): Promise<Item[]> {
  return (await http<ItemListResponse>("/items")).items;
}

export const getPaletteInsights = () => http<PaletteInsights>("/insights/palette");

export async function analyzeItem(input: { image: Blob; category: Category; garment_type: GarmentType; color?: string; item_name?: string }): Promise<AnalyzeResponse> {
  if (!GARMENT_TYPES[input.category].includes(input.garment_type)) throw new ApiError("invalid_request", "That garment type doesn't match the category.");
  const form = new FormData();
  form.append("image", input.image, "item.jpg");
  form.append("category", input.category);
  form.append("garment_type", input.garment_type);
  if (input.color) form.append("color", input.color);
  if (input.item_name) form.append("item_name", input.item_name);
  return http<AnalyzeResponse>("/items/analyze", { method: "POST", body: form });
}

export const saveItem = (temp_handle: string, candidate_index: number) => http<Item>("/items/save", json({ temp_handle, candidate_index }));
export const renameItem = (id: string, name: string) =>
  http<Item>(`/items/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name } satisfies RenameRequest) });
export const rejectItem = (temp_handle: string) => http<{ ok: true }>("/items/reject", json({ temp_handle }));
export async function generateOutfits(limit = 5): Promise<Outfit[]> {
  return (await http<OutfitsGenerateResponse>("/outfits/generate", json({ limit }))).outfits;
}
export const createRender = (req: RenderRequest) => http<RenderJob>("/render", json(req));
export const getRender = (id: string) => http<RenderJob>(`/render/${encodeURIComponent(id)}`);

// Poll a pending render: every 1s for the first 15s, then every 3s, give up at 45s.
// Resolves with the finished job, or null on failure/timeout/abort (callers keep the local composite; never surface an error).
export async function pollRender(id: string, signal: AbortSignal): Promise<RenderJob | null> {
  const start = Date.now();
  while (!signal.aborted) {
    const elapsed = Date.now() - start;
    if (elapsed >= 45_000) return null;
    await new Promise((r) => setTimeout(r, elapsed < 15_000 ? 1000 : 3000));
    if (signal.aborted) return null;
    try {
      const job = await getRender(id);
      if (job.status === "done") return job;
      if (job.status === "failed") return null;
    } catch { /* keep polling until timeout */ }
  }
  return null;
}

// ---------- avatar persistence (per browser) ----------
export type StoredAvatar = { avatar_id: string; wireframe_url: string; avatar_url: string };
const AVATAR_KEY = "atelier:avatar";

export function getStoredAvatar(): StoredAvatar | null {
  try { const v = localStorage.getItem(AVATAR_KEY); return v ? (JSON.parse(v) as StoredAvatar) : null; } catch { return null; }
}
function storeAvatar(a: StoredAvatar): StoredAvatar {
  const slim = { avatar_id: a.avatar_id, wireframe_url: a.wireframe_url, avatar_url: a.avatar_url };
  try { localStorage.setItem(AVATAR_KEY, JSON.stringify(slim)); } catch { /* storage unavailable */ }
  return slim;
}

// Pre-scanned backup avatar: set by the backend/human once the real scan exists.
export const BACKUP_AVATAR_ID = process.env.NEXT_PUBLIC_BACKUP_AVATAR_ID || null;

// ---------- image helpers ----------
// Downscale a camera frame or a picked file to ~1080px on the long edge (latency, not a restriction).
export async function downscale(src: HTMLVideoElement | File, maxEdge = 1080): Promise<Blob> {
  let source: CanvasImageSource, w: number, h: number;
  if (src instanceof HTMLVideoElement) { source = src; w = src.videoWidth; h = src.videoHeight; }
  else {
    try { const bmp = await createImageBitmap(src); source = bmp; w = bmp.width; h = bmp.height; }
    catch { throw new ApiError("unsupported_image", "This file isn't an image we can read."); }
  }
  const s = Math.min(1, maxEdge / Math.max(w, h));
  const c = document.createElement("canvas");
  c.width = Math.round(w * s); c.height = Math.round(h * s);
  c.getContext("2d")?.drawImage(source, 0, 0, c.width, c.height);
  return new Promise((resolve, reject) => c.toBlob((b) => (b ? resolve(b) : reject(new ApiError("unsupported_image", "This file isn't an image we can read."))), "image/jpeg", 0.85));
}

// Demo avatar toggle (menu): its own key; never touches the scanned avatar in AVATAR_KEY.
export const DEMO_AVATAR_ID = process.env.NEXT_PUBLIC_DEMO_AVATAR_ID || BACKUP_AVATAR_ID;
const DEMO_KEY = "atelier:demo-avatar";
export const DEMO_EVENT = "atelier:demo-avatar-change";
export function getDemoOn(): boolean {
  try { return !!DEMO_AVATAR_ID && localStorage.getItem(DEMO_KEY) === "1"; } catch { return false; }
}
export function setDemoOn(on: boolean) {
  try { if (on) localStorage.setItem(DEMO_KEY, "1"); else localStorage.removeItem(DEMO_KEY); } catch { /* storage unavailable */ }
  window.dispatchEvent(new Event(DEMO_EVENT));
}
// Fetch an avatar without storing it (the demo avatar must not replace the scanned one).
export async function fetchAvatarNoStore(id: string): Promise<StoredAvatar> {
  const a = await http<Avatar>(`/avatar/${encodeURIComponent(id)}`);
  return { avatar_id: a.avatar_id, wireframe_url: a.wireframe_url, avatar_url: a.avatar_url };
}

// Planned demo outfits (only used while the demo toggle is ON):
// NEXT_PUBLIC_DEMO_OUTFITS="top_id,bottom_id[,jacket_id];top_id,bottom_id[,jacket_id]"
export type PlannedOutfit = { top_id: string; bottom_id: string; jacket_id: string | null };
export const DEMO_OUTFITS: PlannedOutfit[] = (process.env.NEXT_PUBLIC_DEMO_OUTFITS || "")
  .split(";")
  .map((s) => s.split(",").map((x) => x.trim()).filter(Boolean))
  .filter((p) => p.length >= 2)
  .map(([top_id, bottom_id, jacket_id]) => ({ top_id, bottom_id, jacket_id: jacket_id || null }));
