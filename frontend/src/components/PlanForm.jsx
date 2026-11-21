import React, { useState } from 'react';
import {
  Alert, Autocomplete, Box, Button, Checkbox, FormControlLabel, LinearProgress, MenuItem, Paper, Slider,
  Stack, Switch, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import { api } from '../api.js';
import { fmtDuration } from '../util.js';

const EXAMPLE =
  'Find the best fight scenes, add smooth transitions, use slow motion for important moments, ' +
  'synchronize cuts with the action, and create an engaging gaming video.';

export default function PlanForm({ videos, analyzed, notify, onCreated, goToVideos }) {
  const gameplay = videos.filter((v) => v.role === 'gameplay');
  const references = videos.filter((v) => v.role === 'reference');

  const [selected, setSelected] = useState([]);
  const [reference, setReference] = useState(null);
  const [instructions, setInstructions] = useState(EXAMPLE);
  const [target, setTarget] = useState(30);
  const [format, setFormat] = useState('youtube');
  const [quality, setQuality] = useState('test');
  const [fit, setFit] = useState('crop');
  const [music, setMusic] = useState('');
  const [musicVolume, setMusicVolume] = useState(0.7);
  const [useLlm, setUseLlm] = useState(true);
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
      <Alert severity="info" action={<Button color="inherit" size="small" onClick={goToVideos}>Add videos</Button>}>
        Add at least one gameplay recording first.
      </Alert>
    );
  }

  const unanalyzed = selected.filter((v) => !analyzed.gameplay[v.id]).length;

  return (
    <Paper sx={{ p: 3, maxWidth: 900, mx: 'auto' }}>
      <Stack spacing={3}>
        <Box>
          <Typography variant="h6">Create an editing plan</Typography>
          <Typography variant="body2" color="text.secondary">
            The local Qwen model proposes a plan. Nothing is rendered until you review it.
          </Typography>
        </Box>

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
          helperText={references.length ? 'Its editing style guides the plan.' : 'Add a reference video on the Videos tab to copy its style.'}
        >
          <MenuItem value="">None</MenuItem>
          {references.map((r) => <MenuItem key={r.id} value={r.id}>{r.original_name}</MenuItem>)}
        </TextField>

        <TextField
          label="Editing instructions" multiline minRows={3} value={instructions}
          onChange={(e) => setInstructions(e.target.value)} inputProps={{ maxLength: 2000 }}
        />

        <Box>
          <Typography gutterBottom>Target length: {fmtDuration(target)}</Typography>
          <Slider value={target} min={5} max={300} step={5} onChange={(_, v) => setTarget(v)} />
        </Box>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3}>
          <Box>
            <Typography variant="caption" color="text.secondary">Output format</Typography>
            <ToggleButtonGroup size="small" exclusive fullWidth value={format} onChange={(_, v) => v && setFormat(v)}>
              <ToggleButton value="youtube">YouTube 16:9</ToggleButton>
              <ToggleButton value="instagram">Instagram 9:16</ToggleButton>
            </ToggleButtonGroup>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Quality</Typography>
            <ToggleButtonGroup size="small" exclusive fullWidth value={quality} onChange={(_, v) => v && setQuality(v)}>
              <ToggleButton value="test">Test (fast, small)</ToggleButton>
              <ToggleButton value="full">Full 1080p</ToggleButton>
            </ToggleButtonGroup>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Framing</Typography>
            <ToggleButtonGroup size="small" exclusive fullWidth value={fit} onChange={(_, v) => v && setFit(v)}>
              <ToggleButton value="crop">Fill (crop)</ToggleButton>
              <ToggleButton value="pad">Black bars</ToggleButton>
            </ToggleButtonGroup>
          </Box>
        </Stack>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField
            fullWidth label="Background music file (optional)" placeholder="D:\Music\my_track.mp3"
            value={music} onChange={(e) => setMusic(e.target.value)}
            helperText="Only use music you have permission to use. Cuts are nudged to the beat."
          />
          <Box sx={{ minWidth: 200, px: 1 }}>
            <Typography variant="caption" color="text.secondary">Music volume {Math.round(musicVolume * 100)}%</Typography>
            <Slider value={musicVolume} min={0} max={1.5} step={0.05} onChange={(_, v) => setMusicVolume(v)} disabled={!music.trim()} />
          </Box>
        </Stack>

        <FormControlLabel
          control={<Switch checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />}
          label="Use Qwen 2.5 3B (turn off for the instant rule-based planner)"
        />

        {error && <Alert severity="error" sx={{ whiteSpace: 'pre-wrap' }}>{error}</Alert>}
        {busy && (
          <Box>
            <LinearProgress />
            <Typography variant="caption" color="text.secondary">
              Planning on CPU can take a few minutes. Keep this page open.
            </Typography>
          </Box>
        )}
        <Box>
          <Button
            variant="contained" size="large" startIcon={<AutoFixHighIcon />}
            disabled={busy || selected.length === 0 || instructions.trim().length < 3} onClick={submit}
          >
            Generate plan
          </Button>
        </Box>
      </Stack>
    </Paper>
  );
}
