import React, { useRef, useState } from 'react';
import { Box, Button, CircularProgress, IconButton, LinearProgress, Paper, TextField, Tooltip, Typography } from '@mui/material';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import QueryStatsIcon from '@mui/icons-material/QueryStats';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import MovieIcon from '@mui/icons-material/Movie';
import SportsEsportsIcon from '@mui/icons-material/SportsEsports';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import { api } from '../api.js';
import { fmtDuration } from '../util.js';
import { t } from '../theme.js';
import { EmptyState, FieldLabel, PageHeader, Section, Segmented, Stat } from './ui.jsx';

const VIDEO_EXT = /\.(mp4|mkv|mov|avi|webm)$/i;

function AddVideos({ refresh, notify }) {
  const [role, setRole] = useState('gameplay');
  const [mode, setMode] = useState('path');
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
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

  const onDrop = (e) => {
    e.preventDefault();
    setDrag(false);
    const files = [...e.dataTransfer.files].filter((f) => VIDEO_EXT.test(f.name));
    if (files.length) onFiles(files);
    else notify('Drop video files (mp4, mkv, mov, avi or webm).', 'warning');
  };

  return (
    <Section
      badge="+"
      title="Add videos"
      subtitle="Register recordings from your disk, or upload them. Gameplay is your raw footage; a reference is an edit whose style you want to copy."
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
          <Segmented
            label="This video is a…"
            value={role}
            onChange={setRole}
            options={[
              { value: 'gameplay', label: 'Gameplay recording', icon: <SportsEsportsIcon /> },
              { value: 'reference', label: 'Reference style', icon: <AutoAwesomeIcon /> },
            ]}
          />
          <Segmented
            label="How to add it"
            value={mode}
            onChange={setMode}
            options={[
              { value: 'path', label: 'Use file on this PC', icon: <FolderOpenIcon /> },
              { value: 'upload', label: 'Upload', icon: <CloudUploadIcon /> },
            ]}
          />
        </Box>

        {mode === 'path' ? (
          <Box>
            <FieldLabel hint="No copy is made, so no extra disk space is used. Tip: in Explorer, Shift + right-click the file, then Copy as path.">
              Full path to the video file
            </FieldLabel>
            <Box sx={{ display: 'flex', gap: 1.5, flexDirection: { xs: 'column', sm: 'row' } }}>
              <TextField
                fullWidth size="small" placeholder="D:\Videos\GTA6\fight_01.mp4"
                value={path} onChange={(e) => setPath(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && path.trim() && !busy) onRegister(); }}
              />
              <Button variant="contained" disabled={busy || !path.trim()} onClick={onRegister} sx={{ flexShrink: 0, px: 3 }}>
                Register
              </Button>
            </Box>
          </Box>
        ) : (
          <Box>
            <input
              ref={fileInput} type="file" hidden multiple accept="video/*,.mkv,.mov,.mp4,.avi,.webm"
              onChange={(e) => { const f = [...e.target.files]; e.target.value = ''; if (f.length) onFiles(f); }}
            />
            <Box
              role="button" tabIndex={0}
              onClick={() => !busy && fileInput.current.click()}
              onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && !busy) fileInput.current.click(); }}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={onDrop}
              sx={{
                cursor: busy ? 'default' : 'pointer', textAlign: 'center', px: 3, py: 4.5, borderRadius: '18px',
                border: `2px dashed ${drag ? t.brand : t.lineStrong}`, bgcolor: drag ? t.brandSoft : t.surface2,
                transition: 'all .15s', '&:hover': { borderColor: t.brand, bgcolor: t.brandSoft },
              }}
            >
              <CloudUploadIcon sx={{ fontSize: 38, color: t.brand, mb: 0.5 }} />
              <Typography sx={{ fontWeight: 700 }}>Drop video files here, or click to choose</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                Uploads are copied into the project and need free disk space. For big recordings, use "Use file on this PC".
              </Typography>
            </Box>
          </Box>
        )}
        {busy && <LinearProgress />}
      </Box>
    </Section>
  );
}

function VideoCard({ video, analysis, refresh, notify }) {
  const [busy, setBusy] = useState(false);
  const meta = video.metadata || {};
  const v = meta.video || {};
  const thumbs = video.thumbnail_urls || [];
  const thumb = thumbs[Math.floor((thumbs.length - 1) / 2)];
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

  const badge = (bg, fg, text) => (
    <Box sx={{ px: 1.1, py: 0.35, borderRadius: '8px', bgcolor: bg, color: fg, fontSize: 11.5, fontWeight: 800, lineHeight: 1.4 }}>{text}</Box>
  );

  return (
    <Paper
      sx={{
        borderRadius: '20px', overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '100%',
        boxShadow: t.shadow, transition: 'transform .2s, box-shadow .2s',
        '&:hover': { transform: 'translateY(-3px)', boxShadow: t.shadowLift },
      }}
    >
      <Box sx={{ position: 'relative', aspectRatio: '16 / 9', bgcolor: t.surface2 }}>
        {thumb ? (
          <Box
            component="img" src={api.thumbnailUrl(thumb)} alt=""
            sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
          />
        ) : (
          <Box sx={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: t.lineStrong }}>
            <MovieIcon sx={{ fontSize: 44 }} />
          </Box>
        )}
        <Box sx={{ position: 'absolute', top: 10, left: 10 }}>
          {isRef ? badge(t.tealSoft, t.teal, 'REFERENCE') : badge(t.brandSoft, t.brandDark, 'GAMEPLAY')}
        </Box>
        <Box sx={{ position: 'absolute', bottom: 10, right: 10 }}>
          {badge('rgba(30, 24, 16, 0.78)', '#fff', fmtDuration(meta.duration_seconds))}
        </Box>
      </Box>

      <Box sx={{ p: 2, flexGrow: 1, display: 'flex', flexDirection: 'column', gap: 1.25 }}>
        <Box>
          <Typography sx={{ fontWeight: 700, lineHeight: 1.3 }} noWrap title={video.original_name}>{video.original_name}</Typography>
          <Typography variant="body2" color="text.secondary">
            {v.width}×{v.height} · {Math.round(v.fps || 0)} fps · {meta.audio ? 'with audio' : 'no audio'}
          </Typography>
        </Box>

        {analysis ? (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, color: t.green, fontWeight: 700, fontSize: 13.5 }}>
            <CheckCircleIcon sx={{ fontSize: 18 }} />
            {isRef ? 'Style profile ready' : `${analysis.highlight_count ?? 0} highlight moments found`}
          </Box>
        ) : (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, color: t.amber, fontWeight: 700, fontSize: 13.5 }}>
            <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: t.amber }} />
            Not analyzed yet
          </Box>
        )}

        <Box sx={{ flexGrow: 1 }} />
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Button
            fullWidth size="small" variant={analysis ? 'outlined' : 'contained'} color={analysis ? 'inherit' : 'primary'}
            onClick={analyze} disabled={busy}
            startIcon={busy ? <CircularProgress size={14} color="inherit" /> : <QueryStatsIcon />}
            sx={{ py: 0.9 }}
          >
            {busy ? 'Analyzing…' : analysis ? 'Re-analyze' : 'Analyze'}
          </Button>
          <Tooltip title="Remove from app (keeps your file)">
            <IconButton onClick={remove} aria-label="Remove video" sx={{ color: t.inkSoft, '&:hover': { color: t.red, bgcolor: t.redSoft } }}>
              <DeleteOutlineIcon />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>
      {busy && <LinearProgress />}
    </Paper>
  );
}

function Group({ title, count, hint, children, empty }) {
  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1.25, mb: 0.5 }}>
        <Typography variant="h6" sx={{ fontSize: 20 }}>{title}</Typography>
        <Box sx={{ px: 1, borderRadius: '999px', bgcolor: t.surface2, color: t.inkSoft, fontSize: 12.5, fontWeight: 800 }}>{count}</Box>
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5, maxWidth: 760, lineHeight: 1.6 }}>{hint}</Typography>
      {count === 0 ? empty : (
        <Box sx={{ display: 'grid', gap: 2.5, gridTemplateColumns: 'repeat(auto-fill, minmax(270px, 1fr))' }}>{children}</Box>
      )}
    </Box>
  );
}

export default function VideoLibrary({ videos, analyzed, refresh, notify }) {
  const gameplay = videos.filter((v) => v.role === 'gameplay');
  const reference = videos.filter((v) => v.role === 'reference');
  const analyzedCount = gameplay.filter((v) => analyzed.gameplay[v.id]).length;
  const totalSeconds = gameplay.reduce((sum, v) => sum + (v.metadata?.duration_seconds || 0), 0);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <PageHeader
        eyebrow="Step 1"
        title="Your footage"
        subtitle="Add your gameplay recordings and, optionally, a reference edit. Then analyze them so the editor can find the exciting moments and learn the style."
      />

      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' } }}>
        <Stat icon={<SportsEsportsIcon />} label="Gameplay videos" value={gameplay.length} hint={`${analyzedCount} analyzed`} />
        <Stat icon={<AutoAwesomeIcon />} label="Reference videos" value={reference.length} tone="teal" />
        <Stat icon={<AccessTimeIcon />} label="Raw footage" value={fmtDuration(totalSeconds)} tone="blue" />
      </Box>

      <AddVideos refresh={refresh} notify={notify} />

      <Group
        title="Gameplay recordings" count={gameplay.length}
        hint="Analysis finds candidate highlight moments from motion and audio. These are estimates, not confirmed fights or explosions. It can take a minute or two per video."
        empty={<EmptyState icon={<SportsEsportsIcon />} title="No gameplay yet" body="Add a recording above to get started." />}
      >
        {gameplay.map((v) => (
          <VideoCard key={v.id} video={v} analysis={analyzed.gameplay[v.id]} refresh={refresh} notify={notify} />
        ))}
      </Group>

      <Group
        title="Reference videos" count={reference.length}
        hint="Analysis builds a reusable style profile: cut speed, transitions, slow motion and colour."
        empty={<EmptyState icon={<AutoAwesomeIcon />} title="No reference yet" body="Optional: add an edit you like, and the planner will copy its pacing and style." />}
      >
        {reference.map((v) => (
          <VideoCard key={v.id} video={v} analysis={analyzed.reference[v.id]} refresh={refresh} notify={notify} />
        ))}
      </Group>
    </Box>
  );
}
