// Mirrors backend/avatar/pose_validation.py exactly, so auto-capture only fires when the
// backend will accept the frame. Landmark coordinates from @mediapipe/tasks-vision are already
// normalized to [0, 1] by frame width/height, so fractions (framing, facing offset) work out to
// the same values the backend computes from pixel coordinates -- no width/height needed here.
//
// Keep thresholds and the priority order (most fundamental check first) in sync with the
// backend file; that file's comments explain the reasoning behind each number.
import type { NormalizedLandmark } from "@mediapipe/tasks-vision";

export const VISIBILITY_MIN = 0.3;
export const ARM_ANGLE_MIN_DEG = 12.0;
export const MAX_BODY_FRAME_FRACTION = 0.97;
export const MIN_BODY_FRAME_FRACTION = 0.2;
export const MAX_FACING_OFFSET_RATIO = 0.6;

// MediaPipe BlazePose 33-point indices (same indices backend/avatar/landmarks.py uses).
const IDX = {
  nose: 0,
  leftShoulder: 11,
  rightShoulder: 12,
  leftElbow: 13,
  rightElbow: 14,
  leftWrist: 15,
  rightWrist: 16,
  leftHip: 23,
  rightHip: 24,
  leftKnee: 25,
  rightKnee: 26,
  leftAnkle: 27,
  rightAnkle: 28,
} as const;

const MIN_LANDMARK_COUNT = 29; // highest index used (rightAnkle = 28) + 1

function visibility(lm: NormalizedLandmark[], i: number): number {
  return lm[i]?.visibility ?? 0;
}

function point(lm: NormalizedLandmark[], i: number): [number, number] {
  return [lm[i].x, lm[i].y];
}

function angleDeg(a: [number, number], b: [number, number], c: [number, number]): number {
  const v1: [number, number] = [a[0] - b[0], a[1] - b[1]];
  const v2: [number, number] = [c[0] - b[0], c[1] - b[1]];
  const n1 = Math.hypot(v1[0], v1[1]);
  const n2 = Math.hypot(v2[0], v2[1]);
  if (n1 < 1e-6 || n2 < 1e-6) return 0;
  const cos = Math.max(-1, Math.min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)));
  return (Math.acos(cos) * 180) / Math.PI;
}

/**
 * -> the single most important guidance line for what's failing right now, ordered the same way
 * backend/avatar/pose_validation.py orders its reasons (most-fundamental-first: missing
 * landmarks, then framing, then facing, then arm angle). null means every check the backend
 * would run currently passes.
 */
export function evaluatePose(landmarks: NormalizedLandmark[] | undefined | null): string | null {
  if (!landmarks || landmarks.length < MIN_LANDMARK_COUNT) {
    return "Stand in the frame so your whole body is visible";
  }

  const missingAnkles = Math.min(visibility(landmarks, IDX.leftAnkle), visibility(landmarks, IDX.rightAnkle)) < VISIBILITY_MIN;
  const missingKnees = Math.min(visibility(landmarks, IDX.leftKnee), visibility(landmarks, IDX.rightKnee)) < VISIBILITY_MIN;
  const missingHips = Math.min(visibility(landmarks, IDX.leftHip), visibility(landmarks, IDX.rightHip)) < VISIBILITY_MIN;
  const missingShoulders = Math.min(visibility(landmarks, IDX.leftShoulder), visibility(landmarks, IDX.rightShoulder)) < VISIBILITY_MIN;
  const missingArms = Math.min(
    visibility(landmarks, IDX.leftElbow),
    visibility(landmarks, IDX.rightElbow),
    visibility(landmarks, IDX.leftWrist),
    visibility(landmarks, IDX.rightWrist),
  ) < VISIBILITY_MIN;
  const missingFace = visibility(landmarks, IDX.nose) < VISIBILITY_MIN;

  if (missingAnkles || missingKnees) return "Step back — show your feet";
  if (missingHips) return "Step back — show your waist";
  if (missingShoulders) return "Step back — show your shoulders";
  if (missingArms) return "Show your whole arms";
  if (missingFace) return "Face the camera — show your face";

  // Framing: body height (approx head-top to ankles) as a fraction of the frame height. Only
  // meaningful once face and ankles are located (guaranteed by the checks above).
  const noseY = landmarks[IDX.nose].y;
  const ankleY = Math.max(landmarks[IDX.leftAnkle].y, landmarks[IDX.rightAnkle].y);
  const bodyTop = noseY - (ankleY - noseY) * 0.12;
  const frameFraction = Math.max(1e-6, ankleY - bodyTop);
  if (frameFraction > MAX_BODY_FRAME_FRACTION) return "Step back";
  if (frameFraction < MIN_BODY_FRAME_FRACTION) return "Step closer";

  // Facing the camera: nose offset from the shoulder midpoint, relative to shoulder width.
  const [leftShoulderX] = point(landmarks, IDX.leftShoulder);
  const [rightShoulderX] = point(landmarks, IDX.rightShoulder);
  const shoulderMidX = (leftShoulderX + rightShoulderX) / 2;
  const shoulderWidth = Math.abs(leftShoulderX - rightShoulderX);
  if (shoulderWidth > 1e-6) {
    const offsetRatio = Math.abs(landmarks[IDX.nose].x - shoulderMidX) / shoulderWidth;
    if (offsetRatio > MAX_FACING_OFFSET_RATIO) return "Face the camera";
  }

  // Arms away from the body: hip-shoulder-elbow angle, worst of the two sides.
  let worstAngle = Infinity;
  for (const side of ["left", "right"] as const) {
    const shoulder = point(landmarks, side === "left" ? IDX.leftShoulder : IDX.rightShoulder);
    const hip = point(landmarks, side === "left" ? IDX.leftHip : IDX.rightHip);
    const elbow = point(landmarks, side === "left" ? IDX.leftElbow : IDX.rightElbow);
    const angle = angleDeg(hip, shoulder, elbow);
    if (angle < worstAngle) worstAngle = angle;
  }
  if (worstAngle < ARM_ANGLE_MIN_DEG) return "Arms a little out";

  return null;
}
