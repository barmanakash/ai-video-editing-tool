import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, FormControlLabel, IconButton, MenuItem, Slider,
  Switch, TextField, Tooltip, Typography,
} from '@mui/material';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import AddIcon from '@mui/icons-material/Add';
import SaveIcon from '@mui/icons-material/Save';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import TimelineIcon from '@mui/icons-material/Timeline';
import { api } from '../api.js';
import { EFFECTS, GRADES, PUNCH_MODES, TRANSITIONS, effectiveSeconds, fmtDuration, planSeconds } from '../util.js';
import { t } from '../theme.js';
import { EFFECT_META, FieldLabel, Section } from './ui.jsx';

const num = { type: 'number', size: 'small' };

function Tag({ children, color = t.inkSoft, bg = t.surface2 }) {
  return (
    <Box sx={{ px: 1.25, py: 0.4, borderRadius: '999px', bgcolor: bg, color, fontSize: 12.5, fontWeight: 750, whiteSpace: 'nowrap' }}>
      {children}
    </Box>
  );
}

function Panel({ title, children, sx }) {
  return (
    <Box sx={{ p: 2.25, borderRadius: '16px', bgcolor: t.surface2, ...sx }}>
      <Typography sx={{ fontWeight: 750, fontSize: 14.5, mb: 1.5 }}>{title}</Typography>
      {children}
    </Box>
  );
}

// Proportional bar: one coloured block per clip, sized by how long it runs in the final video.
function TimelineBar({ clips }) {
  const used = [...new Set(clips.map((c) => c.effect))];
  return (
    <Box>
      <Box sx={{ display: 'flex', gap: '3px', height: 46 }}>
        {clips.map((c, i) => {
          const sec = effectiveSeconds(c);
          const meta = EFFECT_META[c.effect] || EFFECT_META.none;
          return (
            <Tooltip key={i} arrow title={`Clip ${i + 1} · ${meta.label} · ${sec.toFixed(1)}s`}>
              <Box
                sx={{
                  flexGrow: Math.max(sec, 0.2), flexBasis: 0, minWidth: 16, bgcolor: meta.color, color: '#fff',
                  display: 'grid', placeItems: 'center', fontSize: 12.5, fontWeight: 800, borderRadius: '8px',
                  '&:first-of-type': { borderTopLeftRadius: '14px', borderBottomLeftRadius: '14px' },
                  '&:last-of-type': { borderTopRightRadius: '14px', borderBottomRightRadius: '14px' },
                }}
              >
                {i + 1}
              </Box>
            </Tooltip>
          );
        })}
      </Box>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mt: 1.25 }}>
        {used.map((e) => {
          const meta = EFFECT_META[e] || EFFECT_META.none;
          return (
            <Box key={e} sx={{ display: 'flex', alignItems: 'center', gap: 0.75, fontSize: 12.5, color: 'text.secondary', fontWeight: 600 }}>
              <Box sx={{ width: 10, height: 10, borderRadius: '3px', bgcolor: meta.color }} />
              {meta.label}
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}

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
    const tr = transitions.slice(0, Math.max(clips.length - 1, 0));
    while (tr.length < clips.length - 1) tr.push('cut');
    edit({ ...plan, clips, transitions: tr });
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
    edit({ ...plan, transitions: plan.transitions.map((tr, idx) => (idx === i ? value : tr)) });

  const setOut = (patch) => edit({ ...plan, output: { ...plan.output, ...patch } });
  const setColor = (patch) => edit({ ...plan, color: { ...plan.color, ...patch } });
  const setAudio = (patch) => edit({ ...plan, audio: { ...plan.audio, ...patch } });
  const setFx = (patch) => edit({ ...plan, fx: { ...(plan.fx || {}), ...patch } });
  const titles = plan.titles || [];
  const setTitle = (i, patch) => edit({ ...plan, titles: titles.map((x, k) => (k === i ? { ...x, ...patch } : x)) });
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
    <Section
      badge={<TimelineIcon />}
      title="Editing plan"
      subtitle="Reorder clips, trim them, change effects and transitions. Save before rendering."
      action={
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Tag color={planner.mode === 'fallback' ? t.amber : t.inkSoft} bg={planner.mode === 'fallback' ? t.amberSoft : t.surface2}>
            {planner.mode === 'fallback' ? 'Rule-based planner' : `Planner: ${planner.mode || 'unknown'}`}
          </Tag>
          <Tag color={t.brandDark} bg={t.brandSoft}>{plan.clips.length} clips · {fmtDuration(total)}</Tag>
        </Box>
      }
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {planner.mode === 'fallback' && (
          <Alert severity="warning">
            Qwen was not used for this plan (rule-based fallback). Check that Ollama is running if you expected the model.
          </Alert>
        )}
        {planner.warnings?.length > 0 && (
          <Accordion disableGutters variant="outlined" sx={{ bgcolor: t.surface }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2" sx={{ fontWeight: 700 }}>Planner notes ({planner.warnings.length})</Typography>
            </AccordionSummary>
            <AccordionDetails>
              {planner.warnings.map((w, i) => <Typography key={i} variant="caption" display="block">• {w}</Typography>)}
            </AccordionDetails>
          </Accordion>
        )}

        <TimelineBar clips={plan.clips} />

        {/* ---------------------------------------------------------- clips */}
        <Box>
          {plan.clips.map((c, i) => (
            <React.Fragment key={i}>
              <Box sx={{ border: `1px solid ${t.line}`, borderRadius: '18px', bgcolor: t.surface, p: 2, boxShadow: '0 1px 2px rgba(74,52,20,0.05)' }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap', mb: 1.75 }}>
                  <Box
                    sx={{
                      width: 32, height: 32, borderRadius: '10px', display: 'grid', placeItems: 'center', flexShrink: 0,
                      bgcolor: (EFFECT_META[c.effect] || EFFECT_META.none).color, color: '#fff', fontWeight: 800, fontSize: 14,
                    }}
                  >
                    {i + 1}
                  </Box>
                  <TextField
                    select size="small" value={c.source} onChange={(e) => setClip(i, { source: e.target.value })}
                    sx={{ flexGrow: 1, minWidth: 180 }}
                  >
                    {gameplay.map((v) => <MenuItem key={v.id} value={v.id}>{v.original_name}</MenuItem>)}
                    {!gameplay.some((v) => v.id === c.source) && <MenuItem value={c.source}>{nameOf(c.source)}</MenuItem>}
                  </TextField>
                  <Tag color={t.inkSoft}>{effectiveSeconds(c).toFixed(1)}s in final video</Tag>
                  <Box sx={{ display: 'flex' }}>
                    <Tooltip title="Move up">
                      <span><IconButton size="small" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUpwardIcon fontSize="small" /></IconButton></span>
                    </Tooltip>
                    <Tooltip title="Move down">
                      <span><IconButton size="small" disabled={i === plan.clips.length - 1} onClick={() => move(i, 1)}><ArrowDownwardIcon fontSize="small" /></IconButton></span>
                    </Tooltip>
                    <Tooltip title="Remove clip">
                      <span>
                        <IconButton size="small" disabled={plan.clips.length < 2} onClick={() => remove(i)} sx={{ '&:hover': { color: t.red, bgcolor: t.redSoft } }}>
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                  </Box>
                </Box>

                <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(auto-fit, minmax(130px, 1fr))' } }}>
                  <TextField {...num} label="Start (s)" value={c.start} inputProps={{ step: 0.1, min: 0 }} onChange={(e) => setClip(i, { start: Number(e.target.value) })} />
                  <TextField {...num} label="End (s)" value={c.end} inputProps={{ step: 0.1, min: 0 }} onChange={(e) => setClip(i, { end: Number(e.target.value) })} />
                  <TextField select size="small" label="Effect" value={c.effect} onChange={(e) => setClip(i, { effect: e.target.value })}>
                    {EFFECTS.map((x) => <MenuItem key={x} value={x}>{EFFECT_META[x]?.label || x}</MenuItem>)}
                  </TextField>
                  <TextField
                    {...num} label={c.effect === 'speed_ramp' ? 'Slowest speed' : 'Speed'} value={c.speed}
                    inputProps={{ step: 0.25, min: 0.25, max: 4 }} onChange={(e) => setClip(i, { speed: Number(e.target.value) })}
                  />
                  {c.effect === 'speed_ramp' && (
                    <TextField
                      {...num} label="Peak at (s)" value={c.peak ?? ''} inputProps={{ step: 0.1, min: 0 }}
                      onChange={(e) => setClip(i, { peak: Number(e.target.value) })}
                    />
                  )}
                </Box>
              </Box>

              {i < plan.clips.length - 1 && (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, pl: 3.5, py: 0.5 }}>
                  <Box sx={{ width: 2, height: 30, bgcolor: t.lineStrong, borderRadius: 1 }} />
                  <TextField
                    select size="small" label="Transition" value={plan.transitions[i] || 'cut'}
                    onChange={(e) => setTransition(i, e.target.value)} sx={{ minWidth: 170 }}
                  >
                    {TRANSITIONS.map((x) => <MenuItem key={x} value={x}>{x}</MenuItem>)}
                  </TextField>
                </Box>
              )}
            </React.Fragment>
          ))}
          <Button size="small" variant="outlined" color="inherit" startIcon={<AddIcon />} onClick={add} sx={{ mt: 1.75 }}>
            Add clip
          </Button>
        </Box>

        {/* ------------------------------------------------------- settings */}
        <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)' } }}>
          <Panel title="Output">
            <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
              <TextField select size="small" label="Format" value={plan.output.format} onChange={(e) => setOut({ format: e.target.value })}>
                <MenuItem value="youtube">YouTube 16:9</MenuItem>
                <MenuItem value="instagram">Instagram 9:16</MenuItem>
              </TextField>
              <TextField select size="small" label="Quality" value={plan.output.quality} onChange={(e) => setOut({ quality: e.target.value })}>
                <MenuItem value="test">Preview 480p</MenuItem>
                <MenuItem value="full">1080p</MenuItem>
                <MenuItem value="1440p">1440p</MenuItem>
                <MenuItem value="4k">4K</MenuItem>
              </TextField>
              <TextField select size="small" label="Framing" value={plan.output.fit} onChange={(e) => setOut({ fit: e.target.value })}>
                <MenuItem value="crop">Crop</MenuItem>
                <MenuItem value="pad">Black bars</MenuItem>
              </TextField>
            </Box>
          </Panel>

          <Panel title="Hit effects">
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
              <TextField select size="small" label="Timing" value={plan.fx?.punch || 'off'} onChange={(e) => setFx({ punch: e.target.value })}>
                {PUNCH_MODES.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
              </TextField>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5 }}>
                <FormControlLabel control={<Switch size="small" checked={plan.fx?.zoom_punch ?? true} onChange={(e) => setFx({ zoom_punch: e.target.checked })} />} label="Zoom" />
                <FormControlLabel control={<Switch size="small" checked={plan.fx?.flash ?? false} onChange={(e) => setFx({ flash: e.target.checked })} />} label="Flash" />
                <FormControlLabel control={<Switch size="small" checked={plan.fx?.shake ?? false} onChange={(e) => setFx({ shake: e.target.checked })} />} label="Shake" />
              </Box>
            </Box>
          </Panel>

          <Panel title="Colour" sx={{ gridColumn: { md: '1 / -1' } }}>
            <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', md: '200px repeat(3, minmax(0, 1fr))' }, alignItems: 'center' }}>
              <TextField select size="small" label="Look" value={plan.color?.preset || 'none'} onChange={(e) => setColor({ preset: e.target.value })}>
                {GRADES.map((g) => <MenuItem key={g} value={g}>{g}</MenuItem>)}
              </TextField>
              {[['brightness', -0.3, 0.3, 0.01], ['contrast', 0.5, 2, 0.05], ['saturation', 0.5, 2, 0.05]].map(([key, min, max, step]) => (
                <Box key={key} sx={{ px: 0.5 }}>
                  <FieldLabel>{key[0].toUpperCase() + key.slice(1)}</FieldLabel>
                  <Slider
                    size="small" min={min} max={max} step={step} valueLabelDisplay="auto"
                    value={plan.color?.[key] ?? (key === 'brightness' ? 0 : 1)} onChange={(_, v) => setColor({ [key]: v })}
                  />
                </Box>
              ))}
            </Box>
          </Panel>

          <Panel title="Titles" sx={{ gridColumn: { md: '1 / -1' } }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              {titles.length === 0 && <Typography variant="body2" color="text.secondary">No on-screen text. Add one if you want a title or end card.</Typography>}
              {titles.map((x, i) => (
                <Box key={i} sx={{ display: 'flex', gap: 1.25, alignItems: 'center', flexWrap: 'wrap' }}>
                  <TextField size="small" label="Text" value={x.text} onChange={(e) => setTitle(i, { text: e.target.value })} inputProps={{ maxLength: 60 }} sx={{ minWidth: 220, flexGrow: 1 }} />
                  <TextField select size="small" label="Position" value={x.position} onChange={(e) => setTitle(i, { position: e.target.value })} sx={{ width: 118 }}>
                    {['center', 'lower', 'top'].map((p) => <MenuItem key={p} value={p}>{p}</MenuItem>)}
                  </TextField>
                  <TextField select size="small" label="Size" value={x.size} onChange={(e) => setTitle(i, { size: e.target.value })} sx={{ width: 118 }}>
                    {['large', 'medium', 'small'].map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
                  </TextField>
                  <TextField select size="small" label="When" value={x.at} onChange={(e) => setTitle(i, { at: e.target.value })} sx={{ width: 110 }}>
                    {['start', 'end', 'time'].map((w) => <MenuItem key={w} value={w}>{w}</MenuItem>)}
                  </TextField>
                  {x.at === 'time' && <TextField {...num} label="At (s)" value={x.start} onChange={(e) => setTitle(i, { start: Number(e.target.value) })} sx={{ width: 96 }} />}
                  <TextField {...num} label="Length (s)" value={x.duration} onChange={(e) => setTitle(i, { duration: Number(e.target.value) })} sx={{ width: 104 }} />
                  <IconButton size="small" onClick={() => removeTitle(i)} aria-label="Remove title"><DeleteOutlineIcon fontSize="small" /></IconButton>
                </Box>
              ))}
              <Box>
                <Button size="small" variant="outlined" color="inherit" startIcon={<AddIcon />} onClick={addTitle} disabled={titles.length >= 6}>
                  Add title
                </Button>
              </Box>
            </Box>
          </Panel>

          {plan.audio?.use_uploaded_music && (
            <Panel title="Music mix" sx={{ gridColumn: { md: '1 / -1' } }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5, wordBreak: 'break-all' }}>
                {plan.audio.music_path}
              </Typography>
              <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)' } }}>
                <Box>
                  <FieldLabel>Music volume · {Math.round(plan.audio.music_volume * 100)}%</FieldLabel>
                  <Slider size="small" min={0} max={1.5} step={0.05} value={plan.audio.music_volume} onChange={(_, v) => setAudio({ music_volume: v })} />
                </Box>
                <Box>
                  <FieldLabel>Game sound volume · {Math.round(plan.audio.game_audio_volume * 100)}%</FieldLabel>
                  <Slider size="small" min={0} max={2} step={0.05} value={plan.audio.game_audio_volume} onChange={(_, v) => setAudio({ game_audio_volume: v })} />
                </Box>
              </Box>
            </Panel>
          )}
        </Box>

        {error && <Alert severity="error" sx={{ whiteSpace: 'pre-wrap' }}>{error.split('; ').join('\n')}</Alert>}

        {(dirty || locked) && (
          <Box
            sx={{
              position: 'sticky', bottom: 16, zIndex: 5, display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap',
              px: 2, py: 1.25, borderRadius: '16px', bgcolor: t.ink, color: '#fff', boxShadow: t.shadowLift,
            }}
          >
            <Typography variant="body2" sx={{ flexGrow: 1, fontWeight: 600 }}>
              {locked ? 'Locked while rendering.' : 'You have unsaved changes. Save before rendering.'}
            </Typography>
            {dirty && !locked && (
              <Button size="small" onClick={() => { setPlan(record.plan); setDirty(false); setError(''); }} sx={{ color: '#fff' }}>
                Discard
              </Button>
            )}
            <Button variant="contained" startIcon={<SaveIcon />} disabled={!dirty || saving || locked} onClick={save}>
              {saving ? 'Saving…' : 'Save changes'}
            </Button>
          </Box>
        )}
      </Box>
    </Section>
  );
}
