"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ApiError, BACKUP_AVATAR_ID, downscale, fetchAvatar, scanAvatar, type StoredAvatar } from "@/lib/api";
import { PoseFigure } from "@/components/PoseFigure";
import { Loader, StatePanel } from "@/components/StatePanel";
import { useAutoCapture } from "@/components/scan/useAutoCapture";

type Step =
  | { s: "consent" }
  | { s: "camera" }
  | { s: "processing" }
  | { s: "rejected"; message: string }
  | { s: "success"; avatar: StoredAvatar; reveal: boolean };

const SCAN_ERRORS = new Set(["pose_rejected", "no_person_detected", "unsupported_image"]);

const SCAN_INSTRUCTIONS = [
  "Stand 6–8 feet back so your whole body — head to feet — is inside the outline",
  "Face the camera",
  "Arms slightly away from your body",
  "Good, even light",
];

// The backend may separate several actionable reasons with "\n" (pose_rejected, no_person_detected,
// unsupported_image). Render each as its own bullet instead of a single run-on sentence.
function RejectionReasons({ message }: { message: string }) {
  const lines = message.split("\n").map((line) => line.trim()).filter(Boolean);
  return (
    <ul className="reject-reasons">
      {(lines.length ? lines : [message]).map((line, i) => <li key={i}>{line}</li>)}
    </ul>
  );
}

export default function ScanPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>({ s: "consent" });
  const [camError, setCamError] = useState(false);
  const [backupId, setBackupId] = useState<string | null>(BACKUP_AVATAR_ID);
  const [autoBackup, setAutoBackup] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [count, setCount] = useState<number | null>(null);
  const countTimer = useRef<number | null>(null);
  const autoStartedRef = useRef(false); // true while the running countdown was auto-triggered, not the shutter

  const clearCountdown = () => { if (countTimer.current !== null) { window.clearInterval(countTimer.current); countTimer.current = null; } setCount(null); };
  useEffect(() => () => { if (countTimer.current !== null) window.clearInterval(countTimer.current); }, []);

  const stop = () => { streamRef.current?.getTracks().forEach((t) => t.stop()); streamRef.current = null; };

  // ?backup=<avatar_id> (or ?backup=1 to use NEXT_PUBLIC_BACKUP_AVATAR_ID) jumps straight to the pre-scanned avatar.
  useEffect(() => {
    const param = new URLSearchParams(window.location.search).get("backup");
    if (param) { setBackupId(param === "1" || param === "true" ? BACKUP_AVATAR_ID : param); setAutoBackup(true); }
  }, []);

  const loadBackup = async () => {
    if (!backupId) { setStep({ s: "rejected", message: "The backup avatar isn't set up yet." }); return; }
    stop();
    setStep({ s: "processing" });
    try { await fetchAvatar(backupId); router.push("/closet"); }
    catch (e) { setStep({ s: "rejected", message: e instanceof ApiError ? e.message : "We couldn't load the backup avatar." }); }
  };

  useEffect(() => { if (autoBackup) void loadBackup() }, [autoBackup]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (step.s !== "camera") return;
    let cancelled = false;
    setCamError(false);
    if (!navigator.mediaDevices?.getUserMedia) { setCamError(true); return; }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", height: { ideal: 1920 } }, audio: false })
      .then((stream) => {
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) { videoRef.current.srcObject = stream; void videoRef.current.play().catch(() => {}); }
      })
      .catch(() => { if (!cancelled) setCamError(true); });
    return () => { cancelled = true; stop(); if (countTimer.current !== null) { window.clearInterval(countTimer.current); countTimer.current = null; } setCount(null); };
  }, [step.s]);

  const submit = async (photo: Blob) => {
    stop();
    setStep({ s: "processing" });
    try {
      const avatar = await scanAvatar(photo);
      setStep({ s: "success", avatar, reveal: false });
      window.setTimeout(() => setStep({ s: "success", avatar, reveal: true }), 1600);
    } catch (e) {
      // Show the backend's specific, actionable reason for scan rejections.
      const message = e instanceof ApiError && (SCAN_ERRORS.has(e.code) || e.code === "network") ? e.message : "The scan didn't go through. Please try again.";
      setStep({ s: "rejected", message });
    }
  };

  const capture = async () => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    try { await submit(await downscale(v)); } catch { setStep({ s: "rejected", message: "We couldn't read that frame. Please try again." }); }
  };

  // 5-second countdown, then capture.
  const startCountdown = () => {
    if (countTimer.current !== null) return;
    let n = 5;
    setCount(n);
    countTimer.current = window.setInterval(() => {
      n -= 1;
      if (n > 0) { setCount(n); return; }
      clearCountdown();
      autoStartedRef.current = false;
      void capture();
    }, 1000);
  };

  // Shutter button: start the countdown, or cancel one already running (manual flow, unchanged).
  const toggleCountdown = () => {
    if (countTimer.current !== null) { clearCountdown(); autoStartedRef.current = false; return; }
    startCountdown();
  };

  // Auto-capture: once every backend pose check has passed continuously for a bit, start the same
  // countdown as the shutter button. If the pose is lost mid-countdown, cancel and resume guidance.
  const handleAutoHold = () => {
    if (countTimer.current !== null || camError) return;
    autoStartedRef.current = true;
    startCountdown();
  };
  const autoCapture = useAutoCapture(videoRef, step.s === "camera" && !camError, handleAutoHold);
  useEffect(() => {
    if (countTimer.current !== null && autoStartedRef.current && autoCapture.status === "active" && !autoCapture.passing) {
      clearCountdown();
      autoStartedRef.current = false;
    }
  }, [autoCapture.passing, autoCapture.status]);

  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    try { await submit(await downscale(file)); }
    catch { setStep({ s: "rejected", message: "That file isn't an image we can read." }); }
  };

  const backupButton = backupId ? <button type="button" className="ghost-btn" onClick={loadBackup}>use backup avatar</button> : null;

  return (
    <main className="flow-page" aria-label="Avatar scan">
      {step.s === "consent" && (
        <StatePanel title="Scan your avatar" actions={<><button type="button" className="solid-btn" onClick={() => setStep({ s: "camera" })}>I agree, continue</button>{backupButton}</>}>
          Your photo is sent to Google&apos;s Gemini API to build your avatar. Stand facing forward with your whole body in the outline.
        </StatePanel>
      )}
      {step.s === "camera" && (
        <div className="camera">
          <div className="camera-frame">
            {!camError && <video ref={videoRef} className="camera-video" playsInline muted />}
            {camError && <p className="camera-fallback">Camera unavailable — upload a full-length photo instead.</p>}
            <PoseFigure className={`pose-overlay${autoCapture.passing ? " pose-overlay--ready" : ""}`} />
            {count !== null && <div className="countdown" role="status" aria-live="assertive">{count}</div>}
          </div>
          {!camError && count === null && autoCapture.status === "active" && (
            <p className="scan-guidance" role="status" aria-live="polite">{autoCapture.guidance ?? "Hold still…"}</p>
          )}
          <ul className="scan-instructions">
            {SCAN_INSTRUCTIONS.map((line) => <li key={line}>{line}</li>)}
          </ul>
          <div className="camera-controls">
            <button type="button" className="ghost-btn" onClick={() => fileRef.current?.click()} disabled={count !== null}>upload</button>
            <button type="button" className="shutter" aria-label={count === null ? "Start 5 second countdown" : "Cancel countdown"} onClick={toggleCountdown} disabled={camError} />
            {backupButton ?? <span />}
          </div>
          <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => { void pickFile(e.target.files?.[0]); e.target.value = ""; }} />
        </div>
      )}
      {step.s === "processing" && (
        <div className="flow-center">
          <PoseFigure className="scan-figure scan-figure--pulse" mesh />
          <Loader label="Reading your silhouette…" />
        </div>
      )}
      {step.s === "rejected" && (
        <StatePanel title="Let's try that again" tone="alert" actions={<><button type="button" className="solid-btn solid-btn--lg" onClick={() => setStep({ s: "camera" })}>Try again</button>{backupButton}</>}>
          <RejectionReasons message={step.message} />
        </StatePanel>
      )}
      {step.s === "success" && (
        <div className="flow-center">
          <div className="avatar-reveal">
            <img src={step.avatar.wireframe_url} alt="" className={`scan-figure${step.reveal ? " is-gone" : ""}`} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
            <img src={step.avatar.avatar_url} alt="Your avatar" className={step.reveal ? "is-shown" : ""} />
          </div>
          {step.reveal && <div className="state-actions"><Link href="/closet" className="solid-btn">go to closet</Link><Link href="/stylist" className="ghost-btn">stylist</Link></div>}
        </div>
      )}
    </main>
  );
}
