import React, { useCallback, useEffect, useState } from 'react';
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, CircularProgress, Typography } from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import { api } from '../api.js';
import { t } from '../theme.js';
import { PageHeader } from './ui.jsx';

// ok: true = good, false = problem, undefined = not reported by the backend
function CheckCard({ label, ok, detail }) {
  const state = ok === true ? 'good' : ok === false ? 'bad' : 'unknown';
  const style = {
    good: { icon: <CheckCircleIcon />, fg: t.green, bg: t.greenSoft },
    bad: { icon: <ErrorIcon />, fg: t.red, bg: t.redSoft },
    unknown: { icon: <HelpOutlineIcon />, fg: t.inkFaint, bg: t.surface2 },
  }[state];
  return (
    <Box
      sx={{
        display: 'flex', gap: 1.75, p: 2, borderRadius: '18px', bgcolor: t.surface,
        border: `1px solid ${state === 'bad' ? t.red : t.line}`, boxShadow: t.shadow, alignItems: 'flex-start',
      }}
    >
      <Box sx={{ width: 40, height: 40, borderRadius: '13px', display: 'grid', placeItems: 'center', bgcolor: style.bg, color: style.fg, flexShrink: 0 }}>
        {style.icon}
      </Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontWeight: 750, lineHeight: 1.3 }}>{label}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-word' }}>
          {detail || (state === 'good' ? 'OK' : state === 'bad' ? 'Needs attention' : 'Not reported')}
        </Typography>
      </Box>
    </Box>
  );
}

export default function SystemStatus({ notify, onChecked }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setData(await api.health());
    } catch (e) {
      setData(null);
      setError(e.message);
      notify(e.message, 'error');
    } finally {
      setLoading(false);
      if (onChecked) onChecked();
    }
  }, [notify, onChecked]);

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const ok = data && (data.ok ?? data.status === 'ok');
  const model = data?.ollama?.required_model || 'qwen2.5:3b';
  const checks = data
    ? [
        { label: 'Python', ok: data.python?.ok, detail: data.python?.version ? `Version ${data.python.version}` : undefined },
        { label: 'FFmpeg', ok: data.ffmpeg?.found, detail: data.ffmpeg?.version },
        { label: 'FFprobe', ok: data.ffprobe?.found, detail: data.ffprobe?.version },
        {
          label: 'Ollama',
          ok: data.ollama?.reachable,
          detail: data.ollama?.reachable ? 'Running' : data.ollama?.error || 'Not reachable',
        },
        {
          label: `AI model ${model}`,
          ok: data.ollama?.model_available,
          detail: data.ollama?.model_available ? 'Installed' : data.ollama?.error,
        },
        {
          label: 'Free disk space',
          ok: data.disk?.ok,
          detail: data.disk?.free_gb != null ? `${data.disk.free_gb} GB free` : undefined,
        },
      ]
    : [];

  return (
    <Box>
      <PageHeader
        eyebrow="Health"
        title="System check"
        subtitle="Everything the editor needs: Python, FFmpeg, Ollama, the qwen2.5:3b model and free disk space."
        actions={
          <Button
            variant="outlined" color="inherit" onClick={load} disabled={loading}
            startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />}
          >
            Re-check
          </Button>
        }
      />

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {error && <Alert severity="error">{error}</Alert>}
        {data && (
          <Alert severity={ok ? 'success' : 'warning'}>
            <strong>{ok ? 'All good.' : 'Something needs attention.'}</strong>{' '}
            {ok ? 'Everything the editor needs is available.' : 'See the cards below for details.'}
          </Alert>
        )}

        {checks.length > 0 && (
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(3, 1fr)' } }}>
            {checks.map((c) => <CheckCard key={c.label} {...c} />)}
          </Box>
        )}

        {data?.issues?.length > 0 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {data.issues.map((msg, i) => <Alert key={i} severity="warning">{msg}</Alert>)}
          </Box>
        )}

        {data && (
          <Accordion disableGutters variant="outlined" sx={{ bgcolor: t.surface }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2" sx={{ fontWeight: 700 }}>Technical details</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Box
                component="pre"
                sx={{
                  m: 0, p: 2, bgcolor: t.surface2, borderRadius: '12px', overflow: 'auto', fontSize: 12.5,
                  fontFamily: '"Cascadia Code", Consolas, monospace',
                }}
              >
                {JSON.stringify(data, null, 2)}
              </Box>
            </AccordionDetails>
          </Accordion>
        )}
      </Box>
    </Box>
  );
}
