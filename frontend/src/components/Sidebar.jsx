import React from 'react';
import { Box, ButtonBase, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';
import MovieFilterIcon from '@mui/icons-material/MovieFilter';
import VideoLibraryIcon from '@mui/icons-material/VideoLibrary';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import MovieIcon from '@mui/icons-material/Movie';
import SettingsIcon from '@mui/icons-material/Settings';
import LockIcon from '@mui/icons-material/Lock';
import { t } from '../theme.js';

export const NAV = [
  { id: 0, label: 'Footage', hint: 'Add and analyze videos', icon: <VideoLibraryIcon /> },
  { id: 1, label: 'Create plan', hint: 'Describe the edit you want', icon: <AutoFixHighIcon /> },
  { id: 2, label: 'Plans & render', hint: 'Review, tweak, export', icon: <MovieIcon /> },
  { id: 3, label: 'System', hint: 'Health checks', icon: <SettingsIcon /> },
];

const HEALTH = {
  checking: { color: t.inkFaint, text: 'Checking system…' },
  ready: { color: t.green, text: 'System ready' },
  attention: { color: t.amber, text: 'Needs attention' },
  offline: { color: t.red, text: 'Backend offline' },
};

export function Brand() {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
      <Box
        sx={{
          width: 40, height: 40, borderRadius: '13px', display: 'grid', placeItems: 'center', color: '#fff',
          background: `linear-gradient(145deg, ${t.brand}, #F0814F)`,
          boxShadow: `0 10px 20px -10px ${alpha(t.brand, 0.9)}`,
        }}
      >
        <MovieFilterIcon />
      </Box>
      <Box>
        <Typography sx={{ fontWeight: 800, fontSize: 17, letterSpacing: '-0.02em', lineHeight: 1.1 }}>Edit Studio</Typography>
        <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Local AI gaming editor</Typography>
      </Box>
    </Box>
  );
}

export default function Sidebar({ tab, onSelect, counts, health }) {
  const h = HEALTH[health] || HEALTH.checking;
  const countFor = { 0: counts.videos, 2: counts.plans };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', p: 2.5 }}>
      <Box sx={{ px: 0.5, pt: 0.5, pb: 3 }}><Brand /></Box>

      <Typography sx={{ px: 1.25, mb: 1, fontSize: 11, fontWeight: 800, letterSpacing: '0.12em', color: t.inkFaint, textTransform: 'uppercase' }}>
        Workflow
      </Typography>

      <Box component="nav" sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        {NAV.map((item) => {
          const active = tab === item.id;
          const count = countFor[item.id];
          return (
            <ButtonBase
              key={item.id}
              onClick={() => onSelect(item.id)}
              aria-current={active ? 'page' : undefined}
              sx={{
                width: '100%', justifyContent: 'flex-start', textAlign: 'left', gap: 1.5,
                px: 1.25, py: 1.1, borderRadius: '14px',
                bgcolor: active ? t.surface : 'transparent',
                border: `1px solid ${active ? t.line : 'transparent'}`,
                boxShadow: active ? t.shadow : 'none',
                transition: 'background-color .15s, box-shadow .15s',
                '&:hover': { bgcolor: active ? t.surface : alpha(t.ink, 0.045) },
              }}
            >
              <Box
                sx={{
                  width: 36, height: 36, borderRadius: '11px', display: 'grid', placeItems: 'center', flexShrink: 0,
                  bgcolor: active ? t.brand : t.surface2, color: active ? '#fff' : t.inkSoft,
                  '& svg': { fontSize: 20 },
                }}
              >
                {item.icon}
              </Box>
              <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                <Typography sx={{ fontWeight: 700, fontSize: 14.5, lineHeight: 1.25, color: active ? t.ink : t.inkSoft }}>
                  {item.label}
                </Typography>
                <Typography sx={{ fontSize: 12, color: t.inkFaint, lineHeight: 1.3 }} noWrap>{item.hint}</Typography>
              </Box>
              {count > 0 && (
                <Box
                  sx={{
                    minWidth: 24, height: 22, px: 0.9, borderRadius: '999px', display: 'grid', placeItems: 'center',
                    bgcolor: active ? t.brandSoft : t.surface2, color: active ? t.brandDark : t.inkSoft,
                    fontSize: 12, fontWeight: 800,
                  }}
                >
                  {count}
                </Box>
              )}
            </ButtonBase>
          );
        })}
      </Box>

      <Box sx={{ flexGrow: 1 }} />

      <ButtonBase
        onClick={() => onSelect(3)}
        sx={{
          width: '100%', justifyContent: 'flex-start', textAlign: 'left', gap: 1.25, p: 1.5, borderRadius: '14px',
          bgcolor: t.surface, border: `1px solid ${t.line}`, '&:hover': { bgcolor: t.surface2 },
        }}
      >
        <Box
          sx={{
            width: 10, height: 10, borderRadius: '50%', bgcolor: h.color, flexShrink: 0,
            boxShadow: `0 0 0 4px ${alpha(h.color, 0.18)}`,
            animation: health === 'checking' ? 'pulse 1.2s ease-in-out infinite' : 'none',
          }}
        />
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontSize: 13.5, fontWeight: 700, lineHeight: 1.25 }}>{h.text}</Typography>
          <Typography sx={{ fontSize: 11.5, color: t.inkFaint, display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <LockIcon sx={{ fontSize: 12 }} /> Runs 100% on this PC
          </Typography>
        </Box>
      </ButtonBase>
    </Box>
  );
}
