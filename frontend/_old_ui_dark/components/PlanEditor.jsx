import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Chip, FormControlLabel, IconButton, MenuItem, Paper, Slider,
  Stack, Switch, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Tooltip, Typography,
} from '@mui/material';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import SaveIcon from '@mui/icons-material/Save';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { api } from '../api.js';
import { EFFECTS, GRADES, PUNCH_MODES, TRANSITIONS, effectiveSeconds, fmtDuration, planSeconds } from '../util.js';

const numberField = { type: 'number', size: 'small', inputProps: { step: 0.1 }, sx: { width: 96 } };

export default function PlanEditor({ record, videos, onSaved, notify }) {
  const gameplay = useMemo(() => videos.filter((v) => v.role === 'gameplay'), [videos]);
  const nameOf = (id) => gameplay.find((v) => v.id === id)?.original_name || id;
  const durationOf = (id) => gameplay.find((v) => v.id === id)?.metadata?.duration_seconds;

  const [plan, setPlan] = useState(record.plan);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setPlan(record.plan);
    setDirty(false);
    setError('');
  }, [record.id, record.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const edit = (next) => { setPlan(next); setDirty(true); };

  // Keep exactly one transition between each pair of clips.
  const withClips = (clips, transitions = plan.transitions) => {
    const t = transitions.slice(0, Math.max(clips.length - 1, 0));
    while (t.length < clips.length - 1) t.push('cut');
    edit({ ...plan, clips, transitions: t });
  };

  const setClip = (i, patch) => {
    const clips = plan.clips.map((c, idx) => (idx === i ? { ...c, ...patch } : c));
    // keep speed and effect consistent: choosing slow motion / speed up sets a sensible speed
    if (patch.effect === 'slow_motion' && clips[i].speed >= 1) clips[i].speed = 0.5;
    if (patch.effect === 'speed_up' && clips[i].speed <= 1) clips[i].speed = 1.5;
    if ((patch.effect === 'none' || patch.effect === 'zoom_in') && clips[i].speed !== 1) clips[i].speed = 1;
    if (patch.effect === 'speed_ramp') {
      if (clips[i].speed >= 1) clips[i].speed = 0.4;
      if (clips[i].peak == null) clips[i].peak = Math.round(((clips[i].start + clips[i].end) / 2) * 10) / 10;
    }
    if (patch.effect && patch.effect !== 'speed_ramp') delete clips[i].peak;
    withClips(clips);
  };

  const move = (i, d) => {
    const clips = [...plan.clips];
    const j = i + d;
    if (j < 0 || j >= clips.length) return;
    [clips[i], clips[j]] = [clips[j], clips[i]];
    withClips(clips);
  };

  const remove = (i) => withClips(plan.clips.filter((_, idx) => idx !== i));

  const add = () => {
    const last = plan.clips[plan.clips.length - 1];
    const source = last?.source || gameplay[0]?.id;
    withClips([...plan.clips, { source, start: 0, end: Math.min(5, durationOf(source) || 5), speed: 1, effect: 'none' }]);
  };

  const setTransition = (i, value) =>
    edit({ ...plan, transitions: plan.transitions.map((t, idx) => (idx === i ? value : t)) });

  const setOut = (patch) => edit({ ...plan, output: { ...plan.output, ...patch } });
  const setColor = (patch) => edit({ ...plan, color: { ...plan.color, ...patch } });
  const setAudio = (patch) => edit({ ...plan, audio: { ...plan.audio, ...patch } });
  const setFx = (patch) => edit({ ...plan, fx: { ...(plan.fx || {}), ...patch } });
  const titles = plan.titles || [];
  const setTitle = (i, patch) => edit({ ...plan, titles: titles.map((t, k) => (k === i ? { ...t, ...patch } : t)) });
  const addTitle = () => edit({ ...plan, titles: [...titles, { text: '', position: 'center', size: 'large', at: 'start', start: 0, duration: 2.5 }] });
  const removeTitle = (i) => edit({ ...plan, titles: titles.filter((_, k) => k !== i) });

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      await api.savePlan(record.id, plan);
      notify('Plan saved', 'success');
      await onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const total = planSeconds(plan.clips);
  const planner = record.planner || {};
  const locked = record.status === 'rendering';

  return (
    <Paper sx={{ p: 2.5 }}>
      <Stack spacing={2.5}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>Editing plan</Typography>
          <Chip size="small" label={`planner: ${planner.mode || 'unknown'}`} color={planner.mode === 'fallback' ? 'warning' : 'default'} />
          <Chip size="small" label={`${plan.clips.length} clips · ${fmtDuration(total)}`} />
          {plan.style && <Chip size="small" variant="outlined" label={plan.style} />}
        </Stack>

        {planner.mode === 'fallback' && (
          <Alert severity="warning">
            Qwen was not used for this plan (rule-based fallback). Check that Ollama is running if you expected the model.
          </Alert>
        )}
        {planner.warnings?.length > 0 && (
          <Accordion disableGutters variant="outlined">
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2">Planner notes ({planner.warnings.length})</Typography>
            </AccordionSummary>
            <AccordionDetails>
              {planner.warnings.map((w, i) => <Typography key={i} variant="caption" display="block">• {w}</Typography>)}
            </AccordionDetails>
          </Accordion>
        )}

        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>#</TableCell><TableCell>Source</TableCell><TableCell>Start (s)</TableCell>
                <TableCell>End (s)</TableCell><TableCell>Effect</TableCell><TableCell>Speed</TableCell>
                <TableCell>Result</TableCell><TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {plan.clips.map((c, i) => (
                <React.Fragment key={i}>
                  <TableRow>
                    <TableCell>{i + 1}</TableCell>
                    <TableCell sx={{ minWidth: 170 }}>
                      <TextField select size="small" fullWidth value={c.source} onChange={(e) => setClip(i, { source: e.target.value })}>
                        {gameplay.map((v) => <MenuItem key={v.id} value={v.id}>{v.original_name}</MenuItem>)}
                        {!gameplay.some((v) => v.id === c.source) && <MenuItem value={c.source}>{nameOf(c.source)}</MenuItem>}
                      </TextField>
                    </TableCell>
                    <TableCell><TextField {...numberField} value={c.start} onChange={(e) => setClip(i, { start: Number(e.target.value) })} /></TableCell>
                    <TableCell><TextField {...numberField} value={c.end} onChange={(e) => setClip(i, { end: Number(e.target.value) })} /></TableCell>
                    <TableCell>
                      <TextField select size="small" value={c.effect} onChange={(e) => setClip(i, { effect: e.target.value })} sx={{ width: 140 }}>
                        {EFFECTS.map((x) => <MenuItem key={x} value={x}>{x.replace('_', ' ')}</MenuItem>)}
                      </TextField>
                    </TableCell>
                    <TableCell>
                      <TextField
                        {...numberField} inputProps={{ step: 0.25, min: 0.25, max: 4 }} value={c.speed}
                        label={c.effect === 'speed_ramp' ? 'slowest' : undefined}
                        onChange={(e) => setClip(i, { speed: Number(e.target.value) })}
                      />
                      {c.effect === 'speed_ramp' && (
                        <TextField
                          {...numberField} label="peak (s)" value={c.peak ?? ''} sx={{ width: 96, mt: 1 }}
                          onChange={(e) => setClip(i, { peak: Number(e.target.value) })}
                        />
                      )}
                    </TableCell>
                    <TableCell>{effectiveSeconds(c).toFixed(1)}s</TableCell>
                    <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                      <Tooltip title="Move up"><span><IconButton size="small" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUpwardIcon fontSize="small" /></IconButton></span></Tooltip>
                      <Tooltip title="Move down"><span><IconButton size="small" disabled={i === plan.clips.length - 1} onClick={() => move(i, 1)}><ArrowDownwardIcon fontSize="small" /></IconButton></span></Tooltip>
                      <Tooltip title="Remove clip"><span><IconButton size="small" disabled={plan.clips.length < 2} onClick={() => remove(i)}><DeleteIcon fontSize="small" /></IconButton></span></Tooltip>
                    </TableCell>
                  </TableRow>
                  {i < plan.clips.length - 1 && (
                    <TableRow>
                      <TableCell />
                      <TableCell colSpan={7} sx={{ py: 0.5, borderBottom: 0 }}>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Typography variant="caption" color="text.secondary">transition to next clip:</Typography>
                          <TextField select size="small" variant="standard" value={plan.transitions[i] || 'cut'} onChange={(e) => setTransition(i, e.target.value)}>
                            {TRANSITIONS.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
                          </TextField>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  )}
                </React.Fragment>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        <Box><Button size="small" startIcon={<AddIcon />} onClick={add}>Add clip</Button></Box>

        <Stack direction={{ xs: 'column', md: 'row' }} spacing={3}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="subtitle2" gutterBottom>Output</Typography>
            <Stack direction="row" spacing={1.5}>
              <TextField select size="small" label="Format" value={plan.output.format} onChange={(e) => setOut({ format: e.target.value })}>
                <MenuItem value="youtube">YouTube 16:9</MenuItem><MenuItem value="instagram">Instagram 9:16</MenuItem>
              </TextField>
              <TextField select size="small" label="Quality" value={plan.output.quality} onChange={(e) => setOut({ quality: e.target.value })}>
                <MenuItem value="test">Test</MenuItem><MenuItem value="full">Full</MenuItem>
              </TextField>
              <TextField select size="small" label="Framing" value={plan.output.fit} onChange={(e) => setOut({ fit: e.target.value })}>
                <MenuItem value="crop">Crop</MenuItem><MenuItem value="pad">Black bars</MenuItem>
              </TextField>
            </Stack>
          </Box>
          <Box sx={{ flex: 1 }}>
            <Typography variant="subtitle2" gutterBottom>Colour</Typography>
            <TextField select size="small" label="Look" value={plan.color?.preset || 'none'} onChange={(e) => setColor({ preset: e.target.value })} sx={{ mb: 1, minWidth: 160 }}>
              {GRADES.map((g) => <MenuItem key={g} value={g}>{g}</MenuItem>)}
            </TextField>
            {[['brightness', -0.3, 0.3, 0.01], ['contrast', 0.5, 2, 0.05], ['saturation', 0.5, 2, 0.05]].map(([key, min, max, step]) => (
              <Stack key={key} direction="row" spacing={2} alignItems="center">
                <Typography variant="caption" sx={{ width: 80 }}>{key}</Typography>
                <Slider size="small" min={min} max={max} step={step} value={plan.color?.[key] ?? (key === 'brightness' ? 0 : 1)} onChange={(_, v) => setColor({ [key]: v })} valueLabelDisplay="auto" />
              </Stack>
            ))}
          </Box>
        </Stack>

        <Box>
          <Typography variant="subtitle2" gutterBottom>Hit effects</Typography>
          <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
            <TextField select size="small" label="Timing" value={plan.fx?.punch || 'off'} onChange={(e) => setFx({ punch: e.target.value })} sx={{ minWidth: 130 }}>
              {PUNCH_MODES.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
            </TextField>
            <FormControlLabel control={<Switch size="small" checked={plan.fx?.zoom_punch ?? true} onChange={(e) => setFx({ zoom_punch: e.target.checked })} />} label="Zoom" />
            <FormControlLabel control={<Switch size="small" checked={plan.fx?.flash ?? false} onChange={(e) => setFx({ flash: e.target.checked })} />} label="Flash" />
            <FormControlLabel control={<Switch size="small" checked={plan.fx?.shake ?? false} onChange={(e) => setFx({ shake: e.target.checked })} />} label="Shake" />
          </Stack>
        </Box>

        <Box>
          <Stack direction="row" alignItems="center" spacing={1}>
            <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>Titles</Typography>
            <Button size="small" startIcon={<AddIcon />} onClick={addTitle} disabled={titles.length >= 6}>Add title</Button>
          </Stack>
          {titles.map((t, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
              <TextField size="small" label="Text" value={t.text} onChange={(e) => setTitle(i, { text: e.target.value })} inputProps={{ maxLength: 60 }} sx={{ minWidth: 220, flexGrow: 1 }} />
              <TextField select size="small" label="Position" value={t.position} onChange={(e) => setTitle(i, { position: e.target.value })} sx={{ width: 110 }}>
                {['center', 'lower', 'top'].map((x) => <MenuItem key={x} value={x}>{x}</MenuItem>)}
              </TextField>
              <TextField select size="small" label="Size" value={t.size} onChange={(e) => setTitle(i, { size: e.target.value })} sx={{ width: 110 }}>
                {['large', 'medium', 'small'].map((x) => <MenuItem key={x} value={x}>{x}</MenuItem>)}
              </TextField>
              <TextField select size="small" label="When" value={t.at} onChange={(e) => setTitle(i, { at: e.target.value })} sx={{ width: 110 }}>
                {['start', 'end', 'time'].map((x) => <MenuItem key={x} value={x}>{x}</MenuItem>)}
              </TextField>
              {t.at === 'time' && <TextField {...numberField} label="At (s)" value={t.start} onChange={(e) => setTitle(i, { start: Number(e.target.value) })} />}
              <TextField {...numberField} label="Length (s)" value={t.duration} onChange={(e) => setTitle(i, { duration: Number(e.target.value) })} />
              <IconButton size="small" onClick={() => removeTitle(i)}><DeleteIcon fontSize="small" /></IconButton>
            </Stack>
          ))}
        </Box>

        {plan.audio?.use_uploaded_music && (
          <Stack direction="row" spacing={2} alignItems="center">
            <Typography variant="subtitle2">Music</Typography>
            <Typography variant="caption" color="text.secondary" noWrap sx={{ flexGrow: 1 }}>{plan.audio.music_path}</Typography>
            <Typography variant="caption">music {Math.round(plan.audio.music_volume * 100)}%</Typography>
            <Slider size="small" sx={{ width: 140 }} min={0} max={1.5} step={0.05} value={plan.audio.music_volume} onChange={(_, v) => setAudio({ music_volume: v })} />
            <Typography variant="caption">game {Math.round(plan.audio.game_audio_volume * 100)}%</Typography>
            <Slider size="small" sx={{ width: 140 }} min={0} max={2} step={0.05} value={plan.audio.game_audio_volume} onChange={(_, v) => setAudio({ game_audio_volume: v })} />
          </Stack>
        )}

        {error && <Alert severity="error" sx={{ whiteSpace: 'pre-wrap' }}>{error.split('; ').join('\n')}</Alert>}
        <Stack direction="row" spacing={1} alignItems="center">
          <Button variant="contained" startIcon={<SaveIcon />} disabled={!dirty || saving || locked} onClick={save}>Save changes</Button>
          {dirty && <Button onClick={() => { setPlan(record.plan); setDirty(false); setError(''); }}>Discard</Button>}
          {dirty && <Typography variant="caption" color="warning.main">Unsaved changes. Save before rendering.</Typography>}
          {locked && <Typography variant="caption" color="text.secondary">Locked while rendering.</Typography>}
        </Stack>
      </Stack>
    </Paper>
  );
}
