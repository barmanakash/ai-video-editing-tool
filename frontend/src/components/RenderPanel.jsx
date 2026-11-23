import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, LinearProgress, Typography } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import DownloadIcon from '@mui/icons-material/Download';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import MovieIcon from '@mui/icons-material/Movie';
import DesktopWindowsIcon from '@mui/icons-material/DesktopWindows';
import SmartphoneIcon from '@mui/icons-material/Smartphone';
import SpeedIcon from '@mui/icons-material/Speed';
import HighQualityIcon from '@mui/icons-material/HighQuality';
import { api } from '../api.js';
import { fmtDuration } from '../util.js';
import { t } from '../theme.js';
import { Section, Segmented } from './ui.jsx';

const ACTIVE = ['queued', 'running'];

function Pill({ children, tone = 'neutral' }) {
  const tones = {
    neutral: [t.surface2, t.inkSoft],
    green: [t.greenSoft, t.green],
    brand: [t.brandSoft, t.brandDark],
  };
  const [bg, fg] = tones[tone];
  return (
    <Box sx={{ px: 1.25, py: 0.4, borderRadius: '999px', bgcolor: bg, color: fg, fontSize: 12.5, fontWeight: 750 }}>{children}</Box>
  );
}

function QualityReport({ report }) {
  if (!report) return null;
  const checks = Array.isArray(report.checks) ? report.checks : [];
  return (
    <Box>
      <Alert severity={report.passed ? 'success' : 'warning'} sx={{ mb: 1.5 }}>
        <strong>{report.passed ? 'Quality check passed.' : 'Quality check failed.'}</strong> {report.summary || ''}
      </Alert>
      {checks.length > 0 && (
        <Box sx={{ display: 'grid', gap: 1, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)' } }}>
          {checks.map((c, i) => {
            const ok = c.ok ?? c.passed;
            return (
              <Box key={i} sx={{ display: 'flex', gap: 1.25, p: 1.25, borderRadius: '12px', bgcolor: t.surface2, alignItems: 'flex-start' }}>
                {ok
                  ? <CheckCircleIcon sx={{ color: t.green, fontSize: 20, mt: '1px' }} />
                  : <ErrorIcon sx={{ color: t.red, fontSize: 20, mt: '1px' }} />}
                <Box sx={{ minWidth: 0 }}>
                  <Typography sx={{ fontSize: 13.5, fontWeight: 700, textTransform: 'capitalize' }}>
                    {String(c.name || c.check || '').replace(/_/g, ' ')}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">{c.detail || c.message}</Typography>
                </Box>
              </Box>
            );
          })}
        </Box>
      )}
      {(report.warnings || []).map((w, i) => (
        <Typography key={i} variant="caption" sx={{ display: 'block', mt: 1, color: t.amber, fontWeight: 600 }}>⚠ {w}</Typography>
      ))}
    </Box>
  );
}

export default function RenderPanel({ record, onChanged, notify }) {
  const [status, setStatus] = useState(null);
  const [format, setFormat] = useState(record.plan.output.format);
  const [quality, setQuality] = useState(record.plan.output.quality);
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

  useEffect(() => {
    setFormat(record.plan.output.format);
    setQuality(record.plan.output.quality);
  }, [record.id, record.plan.output.format, record.plan.output.quality]);

  const start = async () => {
    setBusy(true);
    try {
      const changed = format !== record.plan.output.format || quality !== record.plan.output.quality;
      await api.startRender(record.id, changed ? { format, quality } : undefined);
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
  const percent = job?.progress_percent ?? 0;

  return (
    <Section badge={<MovieIcon />} title="Render" subtitle="Export this plan as a finished video on your computer.">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 2.5 }}>
          <Segmented
            label="Format" value={format} onChange={setFormat} disabled={active}
            options={[
              { value: 'youtube', label: 'YouTube', icon: <DesktopWindowsIcon /> },
              { value: 'instagram', label: 'Instagram', icon: <SmartphoneIcon /> },
            ]}
          />
          <Segmented
            label="Quality" value={quality} onChange={setQuality} disabled={active}
            options={[
              { value: 'test', label: 'Test', icon: <SpeedIcon /> },
              { value: 'full', label: 'Full 1080p', icon: <HighQualityIcon /> },
            ]}
          />
          <Box sx={{ flexGrow: 1 }} />
          {active ? (
            <Button color="error" variant="outlined" size="large" startIcon={<StopIcon />} onClick={cancel}>Cancel render</Button>
          ) : (
            <Button variant="contained" size="large" startIcon={<PlayArrowIcon />} disabled={busy} onClick={start}>
              {ready ? 'Render again' : 'Render video'}
            </Button>
          )}
        </Box>

        {active && (
          <Box sx={{ p: 2.5, borderRadius: '16px', bgcolor: t.blueSoft }}>
            <Box sx={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', mb: 1.25 }}>
              <Typography sx={{ fontWeight: 800, fontSize: 28, letterSpacing: '-0.02em', color: t.blue }}>
                {job.state === 'queued' ? 'Queued' : `${percent}%`}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                elapsed {fmtDuration(job.elapsed_seconds)}
                {job.eta_seconds != null && ` · about ${fmtDuration(job.eta_seconds)} left`}
              </Typography>
            </Box>
            <LinearProgress
              variant={percent > 0 ? 'determinate' : 'indeterminate'} value={percent}
              sx={{ bgcolor: 'rgba(47, 106, 163, 0.16)', '& .MuiLinearProgress-bar': { bgcolor: t.blue } }}
            />
            {job.state === 'queued' && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                Waiting for the previous job to finish…
              </Typography>
            )}
          </Box>
        )}

        {failed && (
          <Alert severity={status.plan_status === 'cancelled' ? 'info' : 'error'} sx={{ whiteSpace: 'pre-wrap' }}>
            {render?.error || job?.error || `Render ${status.plan_status.replace('_', ' ')}.`}
          </Alert>
        )}

        {render?.quality_report && <QualityReport report={render.quality_report} />}

        {ready && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.75 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
              <Pill tone="green">Completed</Pill>
              <Pill>{render.resolution}</Pill>
              <Pill>rendered in {fmtDuration(render.render_seconds)}</Pill>
              {render.beat_snapped_cuts > 0 && <Pill tone="brand">{render.beat_snapped_cuts} cuts synced to music</Pill>}
              <Box sx={{ flexGrow: 1 }} />
              <Button
                variant="outlined" color="inherit" size="small" startIcon={<DownloadIcon />}
                href={api.outputUrl(record.id, render.finished_at)} download={render.output_name}
              >
                Download
              </Button>
            </Box>
            <Box sx={{ p: 1, borderRadius: '20px', bgcolor: '#2A251F', boxShadow: t.shadowLift }}>
              <Box
                component="video" controls preload="metadata" src={api.outputUrl(record.id, render.finished_at)}
                sx={{ display: 'block', width: '100%', maxHeight: 520, bgcolor: '#000', borderRadius: '14px' }}
              />
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
              Saved on this computer: {render.output_path}
            </Typography>
          </Box>
        )}
      </Box>
    </Section>
  );
}
