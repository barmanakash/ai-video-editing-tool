import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Box, Button, CircularProgress, Paper, Stack, Typography } from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import { api } from '../api.js';

export default function SystemStatus({ notify }) {
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
    }
  }, [notify]);

  useEffect(() => { load(); }, [load]);

  const ok = data && (data.ok ?? data.status === 'ok');

  return (
    <Paper sx={{ p: 3, maxWidth: 900, mx: 'auto' }}>
      <Stack spacing={2}>
        <Stack direction="row" alignItems="center">
          <Box sx={{ flexGrow: 1 }}>
            <Typography variant="h6">System check</Typography>
            <Typography variant="body2" color="text.secondary">
              Python, FFmpeg, Ollama, the qwen2.5:3b model and free disk space.
            </Typography>
          </Box>
          <Button startIcon={loading ? <CircularProgress size={16} /> : <RefreshIcon />} onClick={load} disabled={loading}>
            Re-check
          </Button>
        </Stack>
        {error && <Alert severity="error">{error}</Alert>}
        {data && (
          <Alert severity={ok ? 'success' : 'warning'}>
            {ok ? 'Everything the editor needs is available.' : 'Something needs attention. See the details below.'}
          </Alert>
        )}
        {data && (
          <Box component="pre" sx={{ m: 0, p: 2, bgcolor: 'action.hover', borderRadius: 1, overflow: 'auto', fontSize: 13 }}>
            {JSON.stringify(data, null, 2)}
          </Box>
        )}
      </Stack>
    </Paper>
  );
}
