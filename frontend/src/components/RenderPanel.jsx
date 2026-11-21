import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert, Box, Button, Chip, LinearProgress, List, ListItem, ListItemIcon, ListItemText, MenuItem, Paper, Stack,
  TextField, Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import DownloadIcon from '@mui/icons-material/Download';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import { api } from '../api.js';
import { fmtDuration } from '../util.js';

const ACTIVE = ['queued', 'running'];

function QualityReport({ report }) {
  if (!report) return null;
  const checks = Array.isArray(report.checks) ? report.checks : [];
  return (
    <Box>
      <Alert severity={report.passed ? 'success' : 'warning'} sx={{ mb: 1 }}>
        {report.passed ? 'Quality check passed.' : 'Quality check failed.'} {report.summary || ''}
      </Alert>
      {checks.length > 0 && (
        <List dense disablePadding>
          {checks.map((c, i) => (
            <ListItem key={i} disableGutters>
              <ListItemIcon sx={{ minWidth: 32 }}>
                {c.ok ? <CheckCircleIcon color="success" fontSize="small" /> : <ErrorIcon color="error" fontSize="small" />}
              </ListItemIcon>
              <ListItemText primary={String(c.name || c.check || '').replace(/_/g, ' ')} secondary={c.detail || c.message} />
            </ListItem>
          ))}
        </List>
      )}
      {(report.warnings || []).map((w, i) => (
        <Typography key={i} variant="caption" color="warning.main" display="block">⚠ {w}</Typography>
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

  return (
    <Paper sx={{ p: 2.5 }}>
      <Stack spacing={2}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>Render</Typography>
          <TextField select size="small" label="Format" value={format} onChange={(e) => setFormat(e.target.value)} disabled={active}>
            <MenuItem value="youtube">YouTube 16:9</MenuItem>
            <MenuItem value="instagram">Instagram 9:16</MenuItem>
          </TextField>
          <TextField select size="small" label="Quality" value={quality} onChange={(e) => setQuality(e.target.value)} disabled={active}>
            <MenuItem value="test">Test (fast)</MenuItem>
            <MenuItem value="full">Full 1080p</MenuItem>
          </TextField>
          {active ? (
            <Button color="error" variant="outlined" startIcon={<StopIcon />} onClick={cancel}>Cancel</Button>
          ) : (
            <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={busy} onClick={start}>
              {ready ? 'Render again' : 'Render video'}
            </Button>
          )}
        </Stack>

        {active && (
          <Box>
            <LinearProgress
              variant={job.progress_percent > 0 ? 'determinate' : 'indeterminate'}
              value={job.progress_percent}
            />
            <Typography variant="caption" color="text.secondary">
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

        {ready && (
          <Stack spacing={1.5}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Chip size="small" color="success" label="completed" />
              <Chip size="small" label={render.resolution} />
              <Chip size="small" label={`rendered in ${fmtDuration(render.render_seconds)}`} />
              {render.beat_snapped_cuts > 0 && <Chip size="small" label={`${render.beat_snapped_cuts} cuts synced to music`} />}
              <Box sx={{ flexGrow: 1 }} />
              <Button
                size="small" startIcon={<DownloadIcon />}
                href={api.outputUrl(record.id, render.finished_at)} download={render.output_name}
              >
                Download
              </Button>
            </Stack>
            <Box
              component="video" controls preload="metadata" src={api.outputUrl(record.id, render.finished_at)}
              sx={{ width: '100%', maxHeight: 480, bgcolor: 'black', borderRadius: 1 }}
            />
            <Typography variant="caption" color="text.secondary">Saved on this computer: {render.output_path}</Typography>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
