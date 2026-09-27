"use client";
// Auto-capture for the avatar scan camera step. Runs MediaPipe's PoseLandmarker (lite model,
// bundled locally -- see scripts/copy-mediapipe-wasm.mjs) on the live video, evaluates the same
// pose checks the backend runs (lib/poseCheck.ts, mirroring backend/avatar/pose_validation.py),
// and reports live guidance plus whether every check currently passes. The scan page starts its
// existing countdown once `passing` has been continuously true for HOLD_MS, and cancels it if
// `passing` drops back to false mid-countdown.
//
// If the model or its wasm runtime fails to load (blocked, slow device, unsupported browser),
// status becomes "unavailable" and the page's existing manual "take photo" flow is the only path
// -- unchanged.
import { useEffect, useRef, useState, type RefObject } from "react";
import type { PoseLandmarker as PoseLandmarkerType } from "@mediapipe/tasks-vision";
import { evaluatePose } from "@/lib/poseCheck";

export type AutoCaptureStatus = "loading" | "unavailable" | "active";

export interface AutoCaptureState {
  status: AutoCaptureStatus;
  /** The most important failing check, or null when every check currently passes. */
  guidance: string | null;
  /** True once a person is detected and every backend check currently passes. */
  passing: boolean;
}

const DETECT_INTERVAL_MS = 110; // ~9 detections/second
export const HOLD_MS = 1500; // all-checks-pass duration before auto-starting the countdown
const WASM_BASE = "/mediapipe/wasm";
const MODEL_PATH = "/models/pose_landmarker_lite.task";

const IDLE_STATE: AutoCaptureState = { status: "loading", guidance: null, passing: false };

/**
 * @param videoRef the live camera <video> element
 * @param active whether the camera step is showing (detection stops otherwise)
 * @param onHold called once when all checks have passed continuously for HOLD_MS; the caller
 *   starts its existing countdown. Re-arms automatically after the pose is lost and regained.
 */
export function useAutoCapture(
  videoRef: RefObject<HTMLVideoElement | null>,
  active: boolean,
  onHold: () => void,
): AutoCaptureState {
  const [state, setState] = useState<AutoCaptureState>(IDLE_STATE);
  const landmarkerRef = useRef<PoseLandmarkerType | null>(null);
  const loadFailedRef = useRef(false);
  const onHoldRef = useRef(onHold);
  useEffect(() => { onHoldRef.current = onHold; });

  // Load the model once and keep it for the component's lifetime (avoid re-downloading the
  // ~5MB model every time the user returns to the camera step, e.g. after "try again").
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const { FilesetResolver, PoseLandmarker } = await import("@mediapipe/tasks-vision");
        const vision = await FilesetResolver.forVisionTasks(WASM_BASE);
        let landmarker: PoseLandmarkerType;
        try {
          landmarker = await PoseLandmarker.createFromOptions(vision, {
            baseOptions: { modelAssetPath: MODEL_PATH, delegate: "GPU" },
            runningMode: "VIDEO",
            numPoses: 1,
          });
        } catch {
          // Some browsers/devices lack a working GPU delegate; CPU is slower but broadly supported.
          landmarker = await PoseLandmarker.createFromOptions(vision, {
            baseOptions: { modelAssetPath: MODEL_PATH, delegate: "CPU" },
            runningMode: "VIDEO",
            numPoses: 1,
          });
        }
        if (cancelled) { landmarker.close(); return; }
        landmarkerRef.current = landmarker;
      } catch {
        loadFailedRef.current = true;
        if (!cancelled) setState({ status: "unavailable", guidance: null, passing: false });
      }
    }
    void load();
    return () => {
      cancelled = true;
      landmarkerRef.current?.close();
      landmarkerRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!active || loadFailedRef.current) return;
    let rafId: number | null = null;
    let lastRun = 0;
    let holdStart: number | null = null;
    let triggered = false;

    const loop = (now: number) => {
      rafId = requestAnimationFrame(loop);
      const landmarker = landmarkerRef.current;
      const video = videoRef.current;
      if (!landmarker || !video || video.readyState < 2) return;
      if (now - lastRun < DETECT_INTERVAL_MS) return;
      lastRun = now;

      let landmarks;
      try {
        landmarks = landmarker.detectForVideo(video, now).landmarks?.[0];
      } catch {
        return;
      }
      const guidance = evaluatePose(landmarks);
      const passing = guidance === null;

      if (passing) {
        if (holdStart === null) holdStart = now;
        else if (!triggered && now - holdStart >= HOLD_MS) {
          triggered = true;
          onHoldRef.current();
        }
      } else {
        holdStart = null;
        triggered = false;
      }
      setState({ status: "active", guidance, passing });
    };
    rafId = requestAnimationFrame(loop);

    return () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, [active, videoRef]);

  // Reset to a neutral state whenever the camera step goes inactive, so guidance doesn't linger.
  useEffect(() => {
    if (!active) setState((s) => (s.status === "unavailable" ? s : IDLE_STATE));
  }, [active]);

  return state;
}
