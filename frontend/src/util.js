export function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m ? `${m}m ${String(r).padStart(2, '0')}s` : `${r}s`;
}

// Mirrors app/engine/speed_ramp.py so the editor can show the real length of a ramped clip.
export function rampSeconds(clip) {
  const start = Number(clip.start);
  const end = Number(clip.end);
  const length = end - start;
  if (!(length > 0)) return 0;
  const slowest = Math.min(Math.max(Number(clip.speed) || 0.4, 0.25), 1);
  const peak = clip.peak == null ? start + length / 2 : Math.min(Math.max(Number(clip.peak), start), end);
  const w = Math.min(0.3 * length, 2.4);
  const zs = Math.min(Math.max(peak - 1.5 * w, start), end - 3 * w);
  const mid = (1 + slowest) / 2;
  const bounds = [start, zs, zs + w, zs + 2 * w, zs + 3 * w, end];
  const speeds = [1, mid, slowest, mid, 1];
  let total = 0;
  let any = false;
  speeds.forEach((s, i) => {
    const len = bounds[i + 1] - bounds[i];
    if (len >= 0.08) { total += len / s; any = true; }
  });
  return any ? total : length / slowest;
}

export function effectiveSeconds(clip) {
  if (clip.effect === 'speed_ramp') return rampSeconds(clip);
  const speed = Number(clip.speed) || 1;
  return Math.max(0, (Number(clip.end) - Number(clip.start)) / speed);
}

export function planSeconds(clips) {
  return clips.reduce((sum, c) => sum + effectiveSeconds(c), 0);
}

export const EFFECTS = ['none', 'slow_motion', 'speed_up', 'zoom_in', 'speed_ramp'];
export const GRADES = ['none', 'clean', 'vibrant', 'cinematic'];
export const PUNCH_MODES = ['off', 'cuts', 'beats'];
export const TRANSITIONS = ['cut', 'crossfade', 'fadeblack', 'fadewhite', 'slideleft'];

export const STATUS_COLOR = {
  draft: 'default',
  rendering: 'info',
  completed: 'success',
  failed: 'error',
  failed_quality: 'warning',
  cancelled: 'default',
};
