import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Chip, LinearProgress, MenuItem, Stack,
  TextField, Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import DownloadIcon from '@mui/icons-material/Download';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import MovieCreationIcon from '@mui/icons-material/MovieCreation';
import { api } from '../api.js';
import { fmtDuration } from '../util.js';
import { t } from '../theme.js';
import { Section, Segmented } from './ui.jsx';

const ACTIVE = ['queued', 'running'];

const FALLBACK_QUALITIES = [
  { id: 'test', label: 'Preview 480p' },
  { id: 'full', label: 'Full HD 1080p' },
  { id: '1440p', label: '2K 1440p' },
  { id: '4k', label: '4K 2160p' },
];
const QUALITY_SHORT = { test: 'Preview', full: '1080p', '1440p': '1440p', '4k': '4K' };

function QualityReport({ report }) {
  if (!report) return null;
  const checks = Array.isArray(report.checks) ? report.checks : [];
  return (
    <Box>
      <Alert severity={report.passed ? 'success' : 'warning'} sx={{ mb: 1.5 }}>
        {report.passed ? 'Quality check passed.' : 'Quality check failed.'} {report.summary || ''}
      </Alert>
      {checks.length > 0 && (
        <Box sx={{ display: 'grid', gap: 0.75, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
          {checks.map((c, i) => (
            <Box
              key={i}
              sx={{ display: 'flex', gap: 1, alignItems: 'flex-start', p: 1.25, borderRadius: '12px', bgcolor: t.surface2 }}
            >
              {c.ok
                ? <CheckCircleIcon sx={{ color: t.green, fontSize: 20, mt: 0.1 }} />
                : <ErrorIcon sx={{ color: t.red, fontSize: 20, mt: 0.1 }} />}
              <Box sx={{ minWidth: 0 }}>
                <Typography sx={{ fontWeight: 700, fontSize: 13.5, textTransform: 'capitalize' }}>
                  {String(c.name || c.check || '').replace(/_/g, ' ')}
                </Typography>
                <Typography variant="caption" color="text.secondary">{c.detail || c.message}</Typography>
              </Box>
            </Box>
          ))}
        </Box>
      )}
      {(report.warnings || []).map((w, i) => (
        <Typography key={i} variant="caption" sx={{ color: t.amber, display: 'block', mt: 0.75 }}>⚠ {w}</Typography>
      ))}
    </Box>
  );
}

export default function RenderPanel({ record, onChanged, notify }) {
  const out = record.plan.output;
  const [status, setStatus] = useState(null);
  const [opts, setOpts] = useState(null);
  const [estimate, setEstimate] = useState(null);
  const [format, setFormat] = useState(out.format);
  const [quality, setQuality] = useState(out.quality);
  const [fps, setFps] = useState(out.fps || 30);
  const [codec, setCodec] = useState(out.codec || 'h264');
  const [encoder, setEncoder] = useState(out.encoder || 'auto');
  const [level, setLevel] = useState(out.quality_level || 'standard');
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);
  const wasActive = useRef(false);

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api.renderStatus(record.id);
      setStatus(s);
      const active = s.job && ACTIVE.includes(s.job.state);
      if (wasActive.current && !active) {
        wasActive.current = false;
        onChanged();
      }
      wasActive.current = Boolean(active);
      return Boolean(active);
    } catch (e) {
      notify(e.message, 'error');
      return false;
    }
  }, [record.id, onChanged, notify]);

  // Poll while a render is running.
  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      const active = await fetchStatus();
      if (!stopped && active) timer.current = setTimeout(tick, 1500);
    };
    tick();
    return () => { stopped = true; clearTimeout(timer.current); };
  }, [fetchStatus, record.updated_at]);

  // What this computer can export (loaded once; the first call runs small hardware tests).
  useEffect(() => {
    api.exportOptions().then(setOpts).catch(() => setOpts(null));
  }, []);

  useEffect(() => {
    setFormat(out.format);
    setQuality(out.quality);
    setFps(out.fps || 30);
    setCodec(out.codec || 'h264');
    setEncoder(out.encoder || 'auto');
    setLevel(out.quality_level || 'standard');
  }, [record.id, out.format, out.quality, out.fps, out.codec, out.encoder, out.quality_level]); // eslint-disable-line

  // File size / disk check for the chosen settings.
  useEffect(() => {
    const timeout = setTimeout(() => {
      api.estimateExport({
        seconds: Math.max(record.plan.total_duration_estimate || 10, 1),
        format, quality, fps: Number(fps), codec, quality_level: level,
      }).then(setEstimate).catch(() => setEstimate(null));
    }, 300);
    return () => clearTimeout(timeout);
  }, [record.plan.total_duration_estimate, format, quality, fps, codec, level]);

  const start = async () => {
    setBusy(true);
    try {
      const wanted = { format, quality, fps: Number(fps), codec, encoder, quality_level: level };
      const current = {
        format: out.format, quality: out.quality, fps: out.fps || 30,
        codec: out.codec || 'h264', encoder: out.encoder || 'auto', quality_level: out.quality_level || 'standard',
      };
      const changed = Object.fromEntries(Object.entries(wanted).filter(([k, v]) => v !== current[k]));
      await api.startRender(record.id, Object.keys(changed).length ? changed : undefined);
      notify('Render started', 'info');
      await onChanged();
      clearTimeout(timer.current);
      const tick = async () => { if (await fetchStatus()) timer.current = setTimeout(tick, 1500); };
      tick();
    } catch (e) {
      notify(e.message, e.status === 409 ? 'warning' : 'error');
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    try {
      await api.cancelRender(record.id);
      notify('Cancelling...', 'info');
    } catch (e) {
      notify(e.message, 'error');
    }
  };

  const job = status?.job;
  const active = job && ACTIVE.includes(job.state);
  const render = status?.render;
  const ready = status?.plan_status === 'completed' && render?.output_path;
  const failed = ['failed', 'failed_quality', 'cancelled'].includes(status?.plan_status);
  const qualities = opts?.qualities?.length ? opts.qualities : FALLBACK_QUALITIES;
  const qsv = opts?.intel_quick_sync;
  const hevcOk = opts ? opts.codecs?.find((c) => c.id === 'hevc')?.available !== false : true;
  const big = quality === '4k' || quality === '1440p';
  const qualityLabel = (id) => qualities.find((q) => q.id === id)?.label || id;

  return (
    <Section
      badge={<MovieCreationIcon />}
      title="Render"
      subtitle={`${format === 'youtube' ? 'YouTube 16:9' : 'Instagram 9:16'} · ${qualityLabel(quality)} · ${fps} fps`}
      action={
        active ? (
          <Button color="inherit" variant="outlined" startIcon={<StopIcon />} onClick={cancel}>Cancel</Button>
        ) : (
          <Button
            variant="contained" startIcon={<PlayArrowIcon />}
            disabled={busy || estimate?.fits === false} onClick={start}
          >
            {quality === 'test' ? 'Render preview' : ready ? 'Render again' : 'Render video'}
          </Button>
        )
      }
    >
      <Stack spacing={2.25}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2.5} alignItems={{ md: 'flex-end' }} flexWrap="wrap" useFlexGap>
          <Segmented
            label="Format" value={format} onChange={setFormat} disabled={active}
            options={[{ value: 'youtube', label: 'YouTube 16:9' }, { value: 'instagram', label: 'Instagram 9:16' }]}
          />
          <Segmented
            label="Quality" value={quality} onChange={setQuality} disabled={active}
            options={qualities.map((q) => ({ value: q.id, label: QUALITY_SHORT[q.id] || q.label }))}
          />
        </Stack>

        <Accordion disableGutters variant="outlined" disabled={active} sx={{ bgcolor: t.surface }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="body2" sx={{ fontWeight: 650 }}>
              Export settings
              <Typography component="span" variant="body2" color="text.secondary">
                {` · ${fps} fps · ${codec === 'hevc' ? 'HEVC' : 'H.264'} · ${level} quality · encoder ${encoder}`}
              </Typography>
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={2}>
              <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' } }}>
                <TextField select size="small" label="Frame rate" value={fps} onChange={(e) => setFps(e.target.value)}>
                  {[24, 30, 60].map((f) => <MenuItem key={f} value={f}>{f} fps</MenuItem>)}
                </TextField>
                <TextField select size="small" label="Codec" value={codec} onChange={(e) => setCodec(e.target.value)}>
                  <MenuItem value="h264">H.264 (plays everywhere)</MenuItem>
                  <MenuItem value="hevc" disabled={!hevcOk}>HEVC / H.265 (smaller)</MenuItem>
                </TextField>
                <TextField select size="small" label="Encoder" value={encoder} onChange={(e) => setEncoder(e.target.value)}>
                  <MenuItem value="auto">Auto</MenuItem>
                  <MenuItem value="cpu">CPU only</MenuItem>
                  <MenuItem value="qsv">Intel Quick Sync</MenuItem>
                </TextField>
                <TextField select size="small" label="File quality" value={level} onChange={(e) => setLevel(e.target.value)}>
                  <MenuItem value="fast">Fast (smaller)</MenuItem>
                  <MenuItem value="standard">Standard</MenuItem>
                  <MenuItem value="high">High (bigger, slower)</MenuItem>
                </TextField>
              </Box>
              <Typography variant="caption" color="text.secondary">
                Auto uses Intel Quick Sync for 1440p, 4K and HEVC when your computer supports it, and the CPU otherwise.
                If hardware encoding fails, the render automatically retries on the CPU.
              </Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {opts && (
                  <Chip
                    size="small" label={qsv?.h264 ? 'Intel Quick Sync detected' : 'Intel Quick Sync not detected'}
                    sx={{ bgcolor: qsv?.h264 ? t.greenSoft : t.surface2, color: qsv?.h264 ? t.green : t.inkSoft }}
                  />
                )}
                {estimate && (
                  <Chip
                    size="small"
                    label={`${estimate.resolution} · about ${estimate.estimated_mb} MB · ${Math.round(estimate.free_mb / 1024)} GB free`}
                    sx={{ bgcolor: estimate.fits ? t.surface2 : t.redSoft, color: estimate.fits ? t.inkSoft : t.red }}
                  />
                )}
              </Stack>
            </Stack>
          </AccordionDetails>
        </Accordion>

        {quality === 'test' && (
          <Alert severity="info" variant="outlined">
            Preview renders the same edit small and fast (always H.264 on the CPU) so you can check it before the real export.
          </Alert>
        )}
        {big && (
          <Alert severity="warning">
            {quality === '4k' ? '4K' : '1440p'} is slow on this computer{qsv?.h264 ? '' : ' (no Intel Quick Sync detected)'}.
            If your recordings are 1080p, the result is upscaled: a bigger file with no extra detail.
          </Alert>
        )}
        {codec === 'hevc' && (
          <Alert severity="info" variant="outlined">
            HEVC files are smaller, but Windows may need the HEVC video extension to play them. Use H.264 for Instagram.
          </Alert>
        )}
        {estimate?.fits === false && <Alert severity="error">{estimate.note}</Alert>}

        {active && (
          <Box sx={{ p: 2, borderRadius: '14px', bgcolor: t.blueSoft }}>
            <LinearProgress
              variant={job.progress_percent > 0 ? 'determinate' : 'indeterminate'}
              value={job.progress_percent}
              sx={{ bgcolor: 'rgba(255,255,255,0.7)' }}
            />
            <Typography variant="body2" sx={{ mt: 1, fontWeight: 600 }}>
              {job.state === 'queued' ? 'Waiting for the previous job to finish... ' : `${job.progress_percent}% · `}
              elapsed {fmtDuration(job.elapsed_seconds)}
              {job.eta_seconds != null && ` · about ${fmtDuration(job.eta_seconds)} left`}
            </Typography>
          </Box>
        )}

        {failed && (
          <Alert severity={status.plan_status === 'cancelled' ? 'info' : 'error'} sx={{ whiteSpace: 'pre-wrap' }}>
            {render?.error || job?.error || `Render ${status.plan_status.replace('_', ' ')}.`}
          </Alert>
        )}

        {render?.quality_report && <QualityReport report={render.quality_report} />}

        {render?.notes?.length > 0 && (
          <Alert severity="info" variant="outlined" sx={{ alignItems: 'flex-start' }}>
            {render.notes.map((n, i) => <Typography key={i} variant="body2">• {n}</Typography>)}
          </Alert>
        )}

        {ready && (
          <Stack spacing={1.5}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Chip size="small" label="Completed" sx={{ bgcolor: t.greenSoft, color: t.green }} />
              <Chip size="small" label={render.resolution} />
              {render.fps && <Chip size="small" label={`${render.fps} fps`} />}
              {render.encoder && <Chip size="small" label={render.encoder} />}
              {render.size_mb != null && <Chip size="small" label={`${render.size_mb} MB`} />}
              <Chip size="small" label={`rendered in ${fmtDuration(render.render_seconds)}`} />
              {render.beat_snapped_cuts > 0 && <Chip size="small" label={`${render.beat_snapped_cuts} cuts synced to music`} />}
              <Box sx={{ flexGrow: 1 }} />
              <Button
                size="small" variant="outlined" color="inherit" startIcon={<DownloadIcon />}
                href={api.outputUrl(record.id, render.finished_at)} download={render.output_name}
              >
                Download
              </Button>
            </Stack>
            <Box
              component="video" controls preload="metadata" src={api.outputUrl(record.id, render.finished_at)}
              sx={{ width: '100%', maxHeight: 480, bgcolor: '#14110e', borderRadius: '14px' }}
            />
            <Typography variant="caption" color="text.secondary">Saved on this computer: {render.output_path}</Typography>
          </Stack>
        )}
      </Stack>
    </Section>
  );
}
