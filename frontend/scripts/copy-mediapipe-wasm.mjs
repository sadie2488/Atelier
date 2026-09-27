// Copies the @mediapipe/tasks-vision WASM runtime into public/mediapipe/wasm so the
// PoseLandmarker (frontend/components/scan/useAutoCapture.ts) can load it from a same-origin
// path instead of a CDN -- robust against a flaky venue network during a live demo, and pinned
// to the exact version installed (no runtime version-mismatch risk between JS glue and wasm).
// Run via "npm run copy-mediapipe" (wired as predev/prebuild so it stays in sync automatically).
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "node_modules", "@mediapipe", "tasks-vision", "wasm");
const dest = join(here, "..", "public", "mediapipe", "wasm");

if (!existsSync(src)) {
  console.warn(`[copy-mediapipe] source not found at ${src} -- is @mediapipe/tasks-vision installed?`);
  process.exit(0);
}

mkdirSync(dirname(dest), { recursive: true });
cpSync(src, dest, { recursive: true });
console.log(`[copy-mediapipe] copied wasm runtime -> ${dest}`);
