import React, { useState } from 'react';
import {
  Alert, Autocomplete, Box, Button, Checkbox, Chip, FormControlLabel, LinearProgress, MenuItem, Paper, Slider,
  Switch, TextField, Typography,
} from '@mui/material';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import DesktopWindowsIcon from '@mui/icons-material/DesktopWindows';
import SmartphoneIcon from '@mui/icons-material/Smartphone';
import SpeedIcon from '@mui/icons-material/Speed';
import HighQualityIcon from '@mui/icons-material/HighQuality';
import VideoLibraryIcon from '@mui/icons-material/VideoLibrary';
import { api } from '../api.js';
import { fmtDuration } from '../util.js';
import { t } from '../theme.js';
import { EmptyState, FieldLabel, PageHeader, Section, Segmented } from './ui.jsx';

const PRESETS = [
  {
    label: 'Action montage',
    text:
      'Find the best fight scenes, add smooth transitions, use slow motion for important moments, ' +
      'synchronize cuts with the action, and create an engaging gaming video.',
  },
  { label: 'Fast highlights', text: 'A short, punchy highlight reel with fast cuts and only the most intense moments.' },
  { label: 'Cinematic', text: 'A cinematic edit with slow motion on the biggest moments, smooth crossfades and a dramatic build-up.' },
];

function SummaryRow({ label, value }) {
  return (
    <Box
      sx={{
        display: 'flex', justifyContent: 'space-between', gap: 2, py: 1.1,
        borderBottom: `1px solid ${t.line}`, '&:last-of-type': { borderBottom: 0 },
      }}
    >
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 700, textAlign: 'right' }}>{value}</Typography>
    </Box>
  );
}

export default function PlanForm({ videos, analyzed, notify, onCreated, goToVideos }) {
  const gameplay = videos.filter((v) => v.role === 'gameplay');
  const references = videos.filter((v) => v.role === 'reference');

  const [selected, setSelected] = useState([]);
  const [reference, setReference] = useState(null);
  const [instructions, setInstructions] = useState(PRESETS[0].text);
  const [target, setTarget] = useState(30);
  const [format, setFormat] = useState('youtube');
  const [quality, setQuality] = useState('test');
  const [fit, setFit] = useState('crop');
  const [music, setMusic] = useState('');
  const [musicVolume, setMusicVolume] = useState(0.7);
  const [useLlm, setUseLlm] = useState(true);
  const [grade, setGrade] = useState('auto');
  const [punch, setPunch] = useState('auto');
  const [zoomPunch, setZoomPunch] = useState(true);
  const [flash, setFlash] = useState(false);
  const [shake, setShake] = useState(false);
  const [title, setTitle] = useState('');
  const [subtitle, setSubtitle] = useState('');
  const [endText, setEndText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async () => {
    setError('');
    setBusy(true);
    try {
      const body = {
        instructions,
        gameplay_ids: selected.map((v) => v.id),
        reference_id: reference?.id ?? null,
        format, quality, fit,
        target_duration: target,
        music_path: music.trim().replace(/^"|"$/g, '') || null,
        music_volume: musicVolume,
        use_llm: useLlm,
        grade,
        punch,
        zoom_punch: zoomPunch,
        flash,
        shake,
        title: title.trim() || null,
        subtitle: subtitle.trim() || null,
        end_text: endText.trim() || null,
      };
      const record = await api.generatePlan(body);
      onCreated(record);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (gameplay.length === 0) {
    return (
      <Box>
        <PageHeader eyebrow="Step 2" title="Create a plan" subtitle="Describe the video you want and the local AI will propose an edit." />
        <EmptyState
          icon={<VideoLibraryIcon />}
          title="Add a gameplay recording first"
          body="The planner needs at least one gameplay video to pick moments from."
          action={<Button variant="contained" onClick={goToVideos}>Add videos</Button>}
        />
      </Box>
    );
  }

  const unanalyzed = selected.filter((v) => !analyzed.gameplay[v.id]).length;
  const canSubmit = !busy && selected.length > 0 && instructions.trim().length >= 3;

  return (
    <Box>
      <PageHeader
        eyebrow="Step 2"
        title="Create a plan"
        subtitle="Describe the video you want. The local Qwen model proposes an edit, and nothing is rendered until you have reviewed it."
      />

      <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1fr) 340px' }, alignItems: 'start' }}>
        {/* ---------------------------------------------------------------- form */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <Section badge="1" title="Footage" subtitle="Which recordings should the editor pick moments from?">
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Autocomplete
                multiple options={gameplay} value={selected} onChange={(_, v) => setSelected(v)}
                getOptionLabel={(v) => v.original_name} isOptionEqualToValue={(a, b) => a.id === b.id}
                disableCloseOnSelect
                renderOption={(props, v, { selected: sel }) => (
                  <li {...props} key={v.id}>
                    <Checkbox size="small" checked={sel} sx={{ mr: 1 }} />
                    {v.original_name}
                    <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                      {fmtDuration(v.metadata?.duration_seconds)}{analyzed.gameplay[v.id] ? '' : ' · not analyzed'}
                    </Typography>
                  </li>
                )}
                renderInput={(p) => <TextField {...p} label="Gameplay videos (1 to 8)" />}
              />
              {unanalyzed > 0 && (
                <Alert severity="warning">
                  {unanalyzed} selected video(s) have no highlight analysis yet. They will be analyzed automatically,
                  which makes planning slower.
                </Alert>
              )}
              <TextField
                select label="Reference video (optional)" value={reference?.id ?? ''}
                onChange={(e) => setReference(references.find((r) => r.id === e.target.value) ?? null)}
                helperText={references.length ? 'Its editing style guides the plan.' : 'Add a reference video on the Footage page to copy its style.'}
              >
                <MenuItem value="">None</MenuItem>
                {references.map((r) => <MenuItem key={r.id} value={r.id}>{r.original_name}</MenuItem>)}
              </TextField>
            </Box>
          </Section>

          <Section badge="2" title="Direction" subtitle="Tell the editor what you want in plain language.">
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
              <Box>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 1, mb: 1.25 }}>
                  <Typography sx={{ fontSize: 12.5, fontWeight: 700, color: 'text.secondary', mr: 0.5 }}>Quick ideas:</Typography>
                  {PRESETS.map((p) => (
                    <Chip
                      key={p.label} label={p.label} clickable size="small" onClick={() => setInstructions(p.text)}
                      sx={{ bgcolor: instructions === p.text ? t.brandSoft : t.surface2, color: instructions === p.text ? t.brandDark : t.inkSoft }}
                    />
                  ))}
                </Box>
                <TextField
                  fullWidth label="Editing instructions" multiline minRows={3} value={instructions}
                  onChange={(e) => setInstructions(e.target.value)} inputProps={{ maxLength: 2000 }}
                />
              </Box>
              <Box>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <FieldLabel>Target length</FieldLabel>
                  <Typography sx={{ fontWeight: 800, color: t.brandDark }}>{fmtDuration(target)}</Typography>
                </Box>
                <Slider
                  value={target} min={5} max={300} step={5} onChange={(_, v) => setTarget(v)}
                  marks={[{ value: 15, label: '15s' }, { value: 60, label: '1m' }, { value: 180, label: '3m' }, { value: 300, label: '5m' }]}
                  valueLabelDisplay="auto" valueLabelFormat={fmtDuration}
                />
              </Box>
            </Box>
          </Section>

          <Section badge="3" title="Output" subtitle="Where will this video be watched?">
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
              <Segmented
                label="Format" value={format} onChange={setFormat}
                options={[
                  { value: 'youtube', label: 'YouTube 16:9', icon: <DesktopWindowsIcon /> },
                  { value: 'instagram', label: 'Instagram 9:16', icon: <SmartphoneIcon /> },
                ]}
              />
              <Segmented
                label="Quality" value={quality} onChange={setQuality}
                options={[
                  { value: 'test', label: 'Test (fast)', icon: <SpeedIcon /> },
                  { value: 'full', label: 'Full 1080p', icon: <HighQualityIcon /> },
                ]}
              />
              <Segmented
                label="Framing" value={fit} onChange={setFit}
                options={[{ value: 'crop', label: 'Fill (crop)' }, { value: 'pad', label: 'Black bars' }]}
              />
            </Box>
          </Section>

          <Section badge="4" title="Music" subtitle="Optional. Cuts are nudged to land on the beat.">
            <Box sx={{ display: 'flex', gap: 3, flexDirection: { xs: 'column', sm: 'row' }, alignItems: { sm: 'flex-start' } }}>
              <TextField
                fullWidth label="Background music file" placeholder="D:\Music\my_track.mp3"
                value={music} onChange={(e) => setMusic(e.target.value)}
                helperText="Only use music you have permission to use."
              />
              <Box sx={{ minWidth: 210, px: 1, pt: 0.5 }}>
                <FieldLabel>Music volume · {Math.round(musicVolume * 100)}%</FieldLabel>
                <Slider value={musicVolume} min={0} max={1.5} step={0.05} onChange={(_, v) => setMusicVolume(v)} disabled={!music.trim()} />
              </Box>
            </Box>
          </Section>

          <Section
            badge="5" title="Look and effects"
            subtitle="The strongest moment gets an eased speed ramp automatically. Effects hit on the music beats, or on the cuts if there is no music."
          >
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
              <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                <TextField select fullWidth label="Colour look" value={grade} onChange={(e) => setGrade(e.target.value)}>
                  <MenuItem value="auto">Auto (cinematic)</MenuItem>
                  <MenuItem value="none">None</MenuItem>
                  <MenuItem value="clean">Clean and sharp</MenuItem>
                  <MenuItem value="vibrant">Vibrant</MenuItem>
                  <MenuItem value="cinematic">Cinematic</MenuItem>
                </TextField>
                <TextField select fullWidth label="Hit effects timing" value={punch} onChange={(e) => setPunch(e.target.value)}>
                  <MenuItem value="auto">Auto (beats if music, else cuts)</MenuItem>
                  <MenuItem value="off">Off</MenuItem>
                  <MenuItem value="cuts">On the cuts</MenuItem>
                  <MenuItem value="beats">On the music beats</MenuItem>
                </TextField>
              </Box>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, p: 1, px: 2, borderRadius: '14px', bgcolor: t.surface2 }}>
                <FormControlLabel control={<Switch checked={zoomPunch} onChange={(e) => setZoomPunch(e.target.checked)} />} label="Zoom punch" />
                <FormControlLabel control={<Switch checked={flash} onChange={(e) => setFlash(e.target.checked)} />} label="Flash" />
                <FormControlLabel control={<Switch checked={shake} onChange={(e) => setShake(e.target.checked)} />} label="Camera shake" />
              </Box>
              <Box>
                <FieldLabel hint="Letters, digits, spaces and . , ! ? & ( ) + - # @ / are allowed. Other characters are removed.">
                  On-screen text (all optional)
                </FieldLabel>
                <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' } }}>
                  <TextField label="Title at the start" value={title} onChange={(e) => setTitle(e.target.value)} inputProps={{ maxLength: 60 }} />
                  <TextField label="Subtitle" value={subtitle} onChange={(e) => setSubtitle(e.target.value)} inputProps={{ maxLength: 60 }} />
                  <TextField label="End text" value={endText} onChange={(e) => setEndText(e.target.value)} inputProps={{ maxLength: 60 }} />
                </Box>
              </Box>
            </Box>
          </Section>
        </Box>

        {/* ------------------------------------------------------------ summary */}
        <Paper sx={{ borderRadius: '20px', boxShadow: t.shadowLift, p: 3, position: { lg: 'sticky' }, top: { lg: 24 } }}>
          <Typography variant="subtitle1" sx={{ fontSize: 17, mb: 0.5 }}>Your plan</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>Review the settings, then generate.</Typography>
          <Box>
            <SummaryRow label="Videos" value={selected.length ? `${selected.length} selected` : 'None yet'} />
            <SummaryRow label="Reference" value={reference?.original_name || 'None'} />
            <SummaryRow label="Length" value={`about ${fmtDuration(target)}`} />
            <SummaryRow label="Format" value={`${format === 'youtube' ? 'YouTube' : 'Instagram'} · ${quality === 'test' ? 'test' : 'full'}`} />
            <SummaryRow label="Music" value={music.trim() ? 'Yes' : 'No'} />
          </Box>
          <Box sx={{ mt: 1.5, p: 1.5, borderRadius: '14px', bgcolor: t.surface2 }}>
            <FormControlLabel
              sx={{ m: 0, width: '100%', alignItems: 'flex-start' }}
              control={<Switch checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />}
              label={
                <Box sx={{ pt: 0.6 }}>
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>{useLlm ? 'Qwen 2.5 3B planner' : 'Rule-based planner'}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {useLlm ? 'Smarter, but can take a few minutes on CPU.' : 'Instant, no AI model needed.'}
                  </Typography>
                </Box>
              }
            />
          </Box>

          {error && <Alert severity="error" sx={{ mt: 2, whiteSpace: 'pre-wrap' }}>{error}</Alert>}

          <Button
            fullWidth variant="contained" size="large" disabled={!canSubmit} onClick={submit}
            startIcon={<AutoFixHighIcon />} sx={{ mt: 2.5 }}
          >
            {busy ? 'Planning…' : 'Generate plan'}
          </Button>
          {busy && (
            <Box sx={{ mt: 2 }}>
              <LinearProgress />
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                Planning on CPU can take a few minutes. Keep this page open.
              </Typography>
            </Box>
          )}
          {!busy && selected.length === 0 && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.25, textAlign: 'center' }}>
              Choose at least one video to continue.
            </Typography>
          )}
        </Paper>
      </Box>
    </Box>
  );
}
