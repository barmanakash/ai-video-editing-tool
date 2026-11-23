import React, { useCallback, useEffect, useState } from 'react';
import { Box, Button, ButtonBase, CircularProgress, Typography } from '@mui/material';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import AddIcon from '@mui/icons-material/Add';
import MovieIcon from '@mui/icons-material/Movie';
import { api } from '../api.js';
import { fmtDuration } from '../util.js';
import { t } from '../theme.js';
import { EmptyState, PageHeader, StatusChip } from './ui.jsx';
import PlanEditor from './PlanEditor.jsx';
import RenderPanel from './RenderPanel.jsx';

function PlanListItem({ plan, selected, onClick }) {
  return (
    <ButtonBase
      onClick={onClick}
      sx={{
        width: '100%', display: 'block', textAlign: 'left', p: 1.75, borderRadius: '16px',
        bgcolor: selected ? t.surface : 'transparent',
        border: `1px solid ${selected ? t.brand : t.line}`,
        boxShadow: selected ? `0 0 0 3px ${t.brandSoft}` : 'none',
        transition: 'all .15s',
        '&:hover': { bgcolor: t.surface, borderColor: selected ? t.brand : t.lineStrong },
      }}
    >
      <Typography
        sx={{
          fontWeight: 700, fontSize: 14, lineHeight: 1.35, mb: 1,
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }}
      >
        {plan.instructions || plan.id}
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap' }}>
        <StatusChip status={plan.status} />
        <Typography variant="caption" color="text.secondary">
          {plan.clip_count} clips · {fmtDuration(plan.estimated_seconds)}
        </Typography>
      </Box>
    </ButtonBase>
  );
}

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

  const header = (
    <PageHeader
      eyebrow="Step 3"
      title="Plans & render"
      subtitle="Review the plan, adjust clips, effects and transitions, then render your video."
      actions={<Button variant="contained" startIcon={<AddIcon />} onClick={goCreate}>New plan</Button>}
    />
  );

  if (plans.length === 0) {
    return (
      <Box>
        {header}
        <EmptyState
          icon={<MovieIcon />}
          title="No plans yet"
          body="Create a plan and it will show up here, ready to review and render."
          action={<Button variant="contained" onClick={goCreate}>Create a plan</Button>}
        />
      </Box>
    );
  }

  return (
    <Box>
      {header}
      <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', md: '300px minmax(0, 1fr)' }, alignItems: 'start' }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25, position: { md: 'sticky' }, top: { md: 24 }, maxHeight: { md: 'calc(100vh - 48px)' }, overflowY: 'auto', pr: { md: 0.5 } }}>
          <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: '0.12em', color: t.inkFaint, textTransform: 'uppercase', px: 0.5 }}>
            Your plans ({plans.length})
          </Typography>
          {plans.map((p) => (
            <PlanListItem key={p.id} plan={p} selected={p.id === selectedId} onClick={() => onSelect(p.id)} />
          ))}
        </Box>

        <Box sx={{ minWidth: 0 }}>
          {!selectedId && (
            <EmptyState icon={<MovieIcon />} title="Select a plan" body="Pick a plan from the list to review and render it." />
          )}
          {loading && !record && <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>}
          {record && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, flexWrap: 'wrap' }}>
                <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                  <Typography variant="h6" sx={{ fontSize: 19, lineHeight: 1.35 }}>{record.instructions}</Typography>
                  <Box sx={{ mt: 1 }}><StatusChip status={record.status} /></Box>
                </Box>
                <Button size="small" color="inherit" variant="outlined" startIcon={<DeleteOutlineIcon />} onClick={remove}>
                  Delete
                </Button>
              </Box>
              <RenderPanel record={record} onChanged={reload} notify={notify} />
              <PlanEditor record={record} videos={videos} onSaved={reload} notify={notify} />
            </Box>
          )}
        </Box>
      </Box>
    </Box>
  );
}
