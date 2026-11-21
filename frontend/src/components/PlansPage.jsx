import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, Box, Button, Chip, CircularProgress, Grid, List, ListItemButton, ListItemText, Paper, Stack, Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import { api } from '../api.js';
import { STATUS_COLOR, fmtDuration } from '../util.js';
import PlanEditor from './PlanEditor.jsx';
import RenderPanel from './RenderPanel.jsx';

export default function PlansPage({ plans, videos, selectedId, onSelect, refreshPlans, notify, goCreate }) {
  const [record, setRecord] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (id) => {
    if (!id) { setRecord(null); return; }
    setLoading(true);
    try {
      setRecord(await api.getPlan(id));
    } catch (e) {
      setRecord(null);
      notify(e.message, 'error');
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => { load(selectedId); }, [selectedId, load]);

  const reload = useCallback(async () => {
    await load(selectedId);
    await refreshPlans();
  }, [load, selectedId, refreshPlans]);

  const remove = async () => {
    if (!window.confirm('Delete this plan and its rendered video?')) return;
    try {
      await api.deletePlan(record.id, true);
      onSelect(null);
      await refreshPlans();
    } catch (e) {
      notify(e.message, 'error');
    }
  };

  if (plans.length === 0) {
    return (
      <Alert severity="info" action={<Button color="inherit" size="small" onClick={goCreate}>Create plan</Button>}>
        No plans yet.
      </Alert>
    );
  }

  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={3}>
        <Paper>
          <List dense disablePadding>
            {plans.map((p) => (
              <ListItemButton key={p.id} selected={p.id === selectedId} onClick={() => onSelect(p.id)}>
                <ListItemText
                  primary={p.instructions || p.id}
                  primaryTypographyProps={{ noWrap: true }}
                  secondary={
                    <Stack direction="row" spacing={0.5} alignItems="center" component="span" sx={{ mt: 0.5 }}>
                      <Chip size="small" label={p.status} color={STATUS_COLOR[p.status] || 'default'} />
                      <span>{p.clip_count} clips · {fmtDuration(p.estimated_seconds)}</span>
                    </Stack>
                  }
                  secondaryTypographyProps={{ component: 'div' }}
                />
              </ListItemButton>
            ))}
          </List>
        </Paper>
        <Button fullWidth sx={{ mt: 1 }} onClick={goCreate}>New plan</Button>
      </Grid>

      <Grid item xs={12} md={9}>
        {!selectedId && <Alert severity="info">Select a plan on the left.</Alert>}
        {loading && !record && <CircularProgress />}
        {record && (
          <Stack spacing={3}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="h6" sx={{ flexGrow: 1 }} noWrap>{record.instructions}</Typography>
              <Chip label={record.status} color={STATUS_COLOR[record.status] || 'default'} />
              <Button size="small" color="error" startIcon={<DeleteIcon />} onClick={remove}>Delete</Button>
            </Box>
            <RenderPanel record={record} onChanged={reload} notify={notify} />
            <PlanEditor record={record} videos={videos} onSaved={reload} notify={notify} />
          </Stack>
        )}
      </Grid>
    </Grid>
  );
}
