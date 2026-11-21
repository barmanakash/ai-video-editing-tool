import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, AppBar, Box, Container, Snackbar, Tab, Tabs, Toolbar, Typography,
} from '@mui/material';
import MovieFilterIcon from '@mui/icons-material/MovieFilter';
import { api } from './api.js';
import VideoLibrary from './components/VideoLibrary.jsx';
import PlanForm from './components/PlanForm.jsx';
import PlansPage from './components/PlansPage.jsx';
import SystemStatus from './components/SystemStatus.jsx';

export default function App() {
  const [tab, setTab] = useState(0);
  const [videos, setVideos] = useState([]);
  const [analyzed, setAnalyzed] = useState({ gameplay: {}, reference: {} });
  const [plans, setPlans] = useState([]);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [toast, setToast] = useState(null);

  const notify = useCallback((message, severity = 'info') => setToast({ message, severity, key: Date.now() }), []);

  const refreshVideos = useCallback(async () => {
    try {
      const [v, g, r] = await Promise.all([api.listVideos(), api.gameplayAnalyses(), api.referenceProfiles()]);
      setVideos(v.videos || []);
      const gp = {};
      (g.analyses || []).forEach((a) => { gp[a.video_id] = a; });
      const rp = {};
      (r.profiles || []).forEach((p) => { rp[p.video_id ?? p.id] = p; });
      setAnalyzed({ gameplay: gp, reference: rp });
    } catch (e) {
      notify(e.message, 'error');
    }
  }, [notify]);

  const refreshPlans = useCallback(async () => {
    try {
      const p = await api.listPlans();
      setPlans(p.plans || []);
    } catch (e) {
      notify(e.message, 'error');
    }
  }, [notify]);

  useEffect(() => {
    refreshVideos();
    refreshPlans();
  }, [refreshVideos, refreshPlans]);

  const onPlanCreated = (record) => {
    setSelectedPlan(record.id);
    refreshPlans();
    setTab(2);
    notify(`Plan created (${record.planner?.mode || 'unknown'} planner). Review it, then render.`, 'success');
  };

  return (
    <Box sx={{ minHeight: '100vh' }}>
      <AppBar position="sticky" color="default" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Toolbar>
          <MovieFilterIcon sx={{ mr: 1.5 }} color="primary" />
          <Typography variant="h6" sx={{ flexGrow: 1 }}>Local AI Gaming Video Editor</Typography>
          <Typography variant="caption" color="text.secondary">Everything runs on this computer</Typography>
        </Toolbar>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" sx={{ px: 2 }}>
          <Tab label="1. Videos" />
          <Tab label="2. Create plan" />
          <Tab label={`3. Plans & render${plans.length ? ` (${plans.length})` : ''}`} />
          <Tab label="System" />
        </Tabs>
      </AppBar>

      <Container maxWidth="xl" sx={{ py: 3 }}>
        {tab === 0 && (
          <VideoLibrary videos={videos} analyzed={analyzed} refresh={refreshVideos} notify={notify} />
        )}
        {tab === 1 && (
          <PlanForm videos={videos} analyzed={analyzed} notify={notify} onCreated={onPlanCreated} goToVideos={() => setTab(0)} />
        )}
        {tab === 2 && (
          <PlansPage
            plans={plans}
            videos={videos}
            selectedId={selectedPlan}
            onSelect={setSelectedPlan}
            refreshPlans={refreshPlans}
            notify={notify}
            goCreate={() => setTab(1)}
          />
        )}
        {tab === 3 && <SystemStatus notify={notify} />}
      </Container>

      <Snackbar
        key={toast?.key}
        open={Boolean(toast)}
        autoHideDuration={6000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        {toast ? <Alert severity={toast.severity} variant="filled" onClose={() => setToast(null)}>{toast.message}</Alert> : undefined}
      </Snackbar>
    </Box>
  );
}
