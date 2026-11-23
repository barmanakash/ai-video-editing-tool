import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Box, Drawer, IconButton, Snackbar } from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import { api } from './api.js';
import { t } from './theme.js';
import Sidebar, { Brand } from './components/Sidebar.jsx';
import VideoLibrary from './components/VideoLibrary.jsx';
import PlanForm from './components/PlanForm.jsx';
import PlansPage from './components/PlansPage.jsx';
import SystemStatus from './components/SystemStatus.jsx';

const SIDEBAR_WIDTH = 276;

export default function App() {
  const [tab, setTab] = useState(0);
  const [videos, setVideos] = useState([]);
  const [analyzed, setAnalyzed] = useState({ gameplay: {}, reference: {} });
  const [plans, setPlans] = useState([]);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [toast, setToast] = useState(null);
  const [health, setHealth] = useState('checking');
  const [menuOpen, setMenuOpen] = useState(false);

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

  const checkHealth = useCallback(async () => {
    try {
      const h = await api.health();
      setHealth((h.ok ?? h.status === 'ok') ? 'ready' : 'attention');
    } catch {
      setHealth('offline');
    }
  }, []);

  useEffect(() => {
    refreshVideos();
    refreshPlans();
    checkHealth();
    const id = setInterval(checkHealth, 60000);
    return () => clearInterval(id);
  }, [refreshVideos, refreshPlans, checkHealth]);

  const go = (id) => { setTab(id); setMenuOpen(false); window.scrollTo({ top: 0 }); };

  const onPlanCreated = (record) => {
    setSelectedPlan(record.id);
    refreshPlans();
    go(2);
    notify(`Plan created (${record.planner?.mode || 'unknown'} planner). Review it, then render.`, 'success');
  };

  const counts = { videos: videos.length, plans: plans.length };

  return (
    <Box sx={{ minHeight: '100vh' }}>
      {/* Desktop sidebar */}
      <Box
        component="aside"
        sx={{
          display: { xs: 'none', md: 'block' }, position: 'fixed', top: 0, left: 0, bottom: 0, width: SIDEBAR_WIDTH,
          bgcolor: t.sidebar, borderRight: `1px solid ${t.line}`, zIndex: 10,
        }}
      >
        <Sidebar tab={tab} onSelect={go} counts={counts} health={health} />
      </Box>

      {/* Mobile top bar + drawer */}
      <Box
        sx={{
          display: { xs: 'flex', md: 'none' }, alignItems: 'center', gap: 1.5, px: 2, py: 1.25,
          position: 'sticky', top: 0, zIndex: 20, bgcolor: 'rgba(251, 248, 243, 0.92)',
          backdropFilter: 'blur(10px)', borderBottom: `1px solid ${t.line}`,
        }}
      >
        <IconButton onClick={() => setMenuOpen(true)} aria-label="Open menu"><MenuIcon /></IconButton>
        <Brand />
      </Box>
      <Drawer
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        PaperProps={{ sx: { width: SIDEBAR_WIDTH, bgcolor: t.sidebar, border: 0 } }}
        sx={{ display: { md: 'none' } }}
      >
        <Sidebar tab={tab} onSelect={go} counts={counts} health={health} />
      </Drawer>

      <Box component="main" sx={{ ml: { md: `${SIDEBAR_WIDTH}px` }, px: { xs: 2, sm: 3, md: 5 }, py: { xs: 3, md: 5 } }}>
        <Box key={tab} sx={{ maxWidth: 1240, mx: 'auto', animation: 'fadeUp .3s ease both' }}>
          {tab === 0 && (
            <VideoLibrary videos={videos} analyzed={analyzed} refresh={refreshVideos} notify={notify} />
          )}
          {tab === 1 && (
            <PlanForm videos={videos} analyzed={analyzed} notify={notify} onCreated={onPlanCreated} goToVideos={() => go(0)} />
          )}
          {tab === 2 && (
            <PlansPage
              plans={plans}
              videos={videos}
              selectedId={selectedPlan}
              onSelect={setSelectedPlan}
              refreshPlans={refreshPlans}
              notify={notify}
              goCreate={() => go(1)}
            />
          )}
          {tab === 3 && <SystemStatus notify={notify} onChecked={checkHealth} />}
        </Box>
      </Box>

      <Snackbar
        key={toast?.key}
        open={Boolean(toast)}
        autoHideDuration={6000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        {toast ? (
          <Alert severity={toast.severity} variant="filled" onClose={() => setToast(null)} sx={{ boxShadow: t.shadowLift }}>
            {toast.message}
          </Alert>
        ) : undefined}
      </Snackbar>
    </Box>
  );
}
