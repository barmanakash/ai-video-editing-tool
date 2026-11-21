export function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m ? `${m}m ${String(r).padStart(2, '0')}s` : `${r}s`;
}

export function effectiveSeconds(clip) {
  const speed = Number(clip.speed) || 1;
  return Math.max(0, (Number(clip.end) - Number(clip.start)) / speed);
}

export function planSeconds(clips) {
  return clips.reduce((sum, c) => sum + effectiveSeconds(c), 0);
}

export const EFFECTS = ['none', 'slow_motion', 'speed_up', 'zoom_in'];
export const TRANSITIONS = ['cut', 'crossfade', 'fadeblack', 'fadewhite', 'slideleft'];

export const STATUS_COLOR = {
  draft: 'default',
  rendering: 'info',
  completed: 'success',
  failed: 'error',
  failed_quality: 'warning',
  cancelled: 'default',
};
