import React, { useRef, useState } from 'react';
import {
  Alert, Box, Button, Card, CardActions, CardContent, CardMedia, Chip, CircularProgress, Grid,
  LinearProgress, Paper, Stack, Tab, Tabs, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import QueryStatsIcon from '@mui/icons-material/QueryStats';
import DeleteIcon from '@mui/icons-material/Delete';
import { api } from '../api.js';
import { fmtDuration } from '../util.js';

function AddVideos({ refresh, notify }) {
  const [role, setRole] = useState('gameplay');
  const [mode, setMode] = useState(0);
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const fileInput = useRef(null);

  const run = async (fn) => {
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  };

  const onFiles = (files) =>
    run(async () => {
      for (const file of files) {
        await api.uploadVideo(file, role);
        notify(`Added ${file.name}`, 'success');
      }
    });

  const onRegister = () =>
    run(async () => {
      const v = await api.registerVideo(path.trim().replace(/^"|"$/g, ''), role);
      notify(`Registered ${v.original_name}`, 'success');
      setPath('');
    });

  return (
    <Paper sx={{ p: 2.5 }}>
      <Stack spacing={2}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Add videos as</Typography>
          <ToggleButtonGroup size="small" exclusive value={role} onChange={(_, v) => v && setRole(v)}>
            <ToggleButton value="gameplay">Gameplay recording</ToggleButton>
            <ToggleButton value="reference">Reference (style to copy)</ToggleButton>
          </ToggleButtonGroup>
        </Stack>

        <Tabs value={mode} onChange={(_, v) => setMode(v)}>
          <Tab icon={<FolderOpenIcon />} iconPosition="start" label="Use file on this PC (recommended)" />
          <Tab icon={<UploadFileIcon />} iconPosition="start" label="Upload" />
        </Tabs>

        {mode === 0 ? (
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
            <TextField
              fullWidth size="small" label="Full path to the video file"
              placeholder="D:\Videos\GTA6\fight_01.mp4"
              value={path} onChange={(e) => setPath(e.target.value)}
              helperText="No copy is made, so no extra disk space is used. Tip: in Explorer, Shift + right-click > Copy as path."
            />
            <Box>
              <Button variant="contained" disabled={busy || !path.trim()} onClick={onRegister}>Register</Button>
            </Box>
          </Stack>
        ) : (
          <Box>
            <input
              ref={fileInput} type="file" hidden multiple accept="video/*,.mkv,.mov,.mp4,.avi,.webm"
              onChange={(e) => { const f = [...e.target.files]; e.target.value = ''; if (f.length) onFiles(f); }}
            />
            <Button variant="contained" startIcon={<UploadFileIcon />} disabled={busy} onClick={() => fileInput.current.click()}>
              Choose video files
            </Button>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
              Uploads are copied into the project (needs free disk space). For big recordings use the file path option.
            </Typography>
          </Box>
        )}
        {busy && <LinearProgress />}
      </Stack>
    </Paper>
  );
}

function VideoCard({ video, analysis, refresh, notify }) {
  const [busy, setBusy] = useState(false);
  const meta = video.metadata || {};
  const v = meta.video || {};
  const thumb = video.thumbnail_urls?.[Math.floor((video.thumbnail_urls.length - 1) / 2)];
  const isRef = video.role === 'reference';

  const analyze = async () => {
    setBusy(true);
    try {
      if (isRef) await api.analyzeReference(video.id);
      else await api.analyzeGameplay(video.id);
      notify(`${isRef ? 'Style profile' : 'Highlight analysis'} ready for ${video.original_name}`, 'success');
      await refresh();
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Remove "${video.original_name}" from the app? Your original file is not deleted.`)) return;
    try {
      await api.deleteVideo(video.id);
      await refresh();
    } catch (e) {
      notify(e.message, 'error');
    }
  };

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {thumb ? (
        <CardMedia component="img" height="150" image={api.thumbnailUrl(thumb)} alt="" sx={{ objectFit: 'cover' }} />
      ) : (
        <Box sx={{ height: 150, bgcolor: 'action.hover' }} />
      )}
      <CardContent sx={{ flexGrow: 1 }}>
        <Typography variant="subtitle2" noWrap title={video.original_name}>{video.original_name}</Typography>
        <Typography variant="caption" color="text.secondary" display="block">
          {fmtDuration(meta.duration_seconds)} · {v.width}x{v.height} · {Math.round(v.fps || 0)} fps
        </Typography>
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
          <Chip size="small" label={video.role} color={isRef ? 'secondary' : 'primary'} variant="outlined" />
          <Chip size="small" label={meta.audio ? 'audio' : 'no audio'} variant="outlined" />
          {analysis ? (
            <Chip
              size="small" color="success"
              label={isRef ? 'style profile ready' : `${analysis.highlight_count ?? 0} highlights`}
            />
          ) : (
            <Chip size="small" label="not analyzed" />
          )}
        </Stack>
      </CardContent>
      <CardActions>
        <Button
          size="small" onClick={analyze} disabled={busy}
          startIcon={busy ? <CircularProgress size={14} /> : <QueryStatsIcon />}
        >
          {analysis ? 'Re-analyze' : 'Analyze'}
        </Button>
        <Box sx={{ flexGrow: 1 }} />
        <Button size="small" color="error" onClick={remove} startIcon={<DeleteIcon />}>Remove</Button>
      </CardActions>
    </Card>
  );
}

export default function VideoLibrary({ videos, analyzed, refresh, notify }) {
  const gameplay = videos.filter((v) => v.role === 'gameplay');
  const reference = videos.filter((v) => v.role === 'reference');

  const section = (title, items, kind, hint) => (
    <Box>
      <Typography variant="h6" sx={{ mb: 0.5 }}>{title} ({items.length})</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{hint}</Typography>
      {items.length === 0 ? (
        <Alert severity="info" variant="outlined">Nothing here yet.</Alert>
      ) : (
        <Grid container spacing={2}>
          {items.map((v) => (
            <Grid item xs={12} sm={6} md={4} lg={3} key={v.id}>
              <VideoCard video={v} analysis={analyzed[kind][v.id]} refresh={refresh} notify={notify} />
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  );

  return (
    <Stack spacing={4}>
      <AddVideos refresh={refresh} notify={notify} />
      {section('Gameplay recordings', gameplay, 'gameplay',
        'Analysis finds candidate highlight moments from motion and audio. These are estimates, not confirmed fights or explosions. Analysis can take a minute or two per video.')}
      {section('Reference videos', reference, 'reference',
        'Analysis builds a reusable style profile (cut speed, transitions, slow motion, colour).')}
    </Stack>
  );
}
