import React from 'react';
import { Box, Paper, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import { t } from '../theme.js';

// Colours used for each clip effect (timeline bar, legends).
export const EFFECT_META = {
  none: { label: 'Normal', color: '#CDBFA8' },
  slow_motion: { label: 'Slow motion', color: t.blue },
  speed_up: { label: 'Speed up', color: t.amber },
  zoom_in: { label: 'Zoom in', color: t.teal },
  speed_ramp: { label: 'Speed ramp', color: t.brand },
};

export function PageHeader({ eyebrow, title, subtitle, actions }) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: { xs: 'column', sm: 'row' },
        alignItems: { xs: 'flex-start', sm: 'flex-end' },
        gap: 2,
        mb: 3.5,
      }}
    >
      <Box sx={{ flexGrow: 1, minWidth: 0 }}>
        {eyebrow && (
          <Typography sx={{ color: t.brand, fontWeight: 800, fontSize: 12, letterSpacing: '0.1em', textTransform: 'uppercase', mb: 0.75 }}>
            {eyebrow}
          </Typography>
        )}
        <Typography variant="h4" component="h1" sx={{ fontSize: { xs: 26, md: 34 } }}>{title}</Typography>
        {subtitle && <Typography color="text.secondary" sx={{ mt: 1, maxWidth: 720, lineHeight: 1.6 }}>{subtitle}</Typography>}
      </Box>
      {actions && <Box sx={{ display: 'flex', gap: 1, flexShrink: 0 }}>{actions}</Box>}
    </Box>
  );
}

// A titled card. `badge` is a small leading element (step number or icon).
export function Section({ badge, title, subtitle, action, children, sx, contentSx }) {
  return (
    <Paper sx={{ borderRadius: '20px', boxShadow: t.shadow, overflow: 'hidden', ...sx }}>
      {(title || action) && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, px: { xs: 2.5, md: 3 }, pt: 2.5, pb: 0.5 }}>
          {badge && (
            <Box
              sx={{
                width: 34, height: 34, borderRadius: '11px', flexShrink: 0,
                display: 'grid', placeItems: 'center',
                bgcolor: t.brandSoft, color: t.brandDark, fontWeight: 800, fontSize: 15,
                '& svg': { fontSize: 20 },
              }}
            >
              {badge}
            </Box>
          )}
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="subtitle1" sx={{ fontSize: 17, lineHeight: 1.25 }}>{title}</Typography>
            {subtitle && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>{subtitle}</Typography>}
          </Box>
          {action}
        </Box>
      )}
      <Box sx={{ px: { xs: 2.5, md: 3 }, pt: 2, pb: { xs: 2.5, md: 3 }, ...contentSx }}>{children}</Box>
    </Paper>
  );
}

export function FieldLabel({ children, hint }) {
  return (
    <Box sx={{ mb: 0.75 }}>
      <Typography sx={{ fontSize: 12.5, fontWeight: 700, color: 'text.secondary' }}>{children}</Typography>
      {hint && <Typography sx={{ fontSize: 12, color: t.inkFaint }}>{hint}</Typography>}
    </Box>
  );
}

// A labelled pill-style choice control (replaces plain toggle buttons).
export function Segmented({ label, hint, value, onChange, options, fullWidth, disabled }) {
  return (
    <Box>
      {label && <FieldLabel hint={hint}>{label}</FieldLabel>}
      <ToggleButtonGroup
        exclusive
        size="small"
        fullWidth={fullWidth}
        disabled={disabled}
        value={value}
        onChange={(_, v) => { if (v !== null) onChange(v); }}
      >
        {options.map((o) => (
          <ToggleButton key={o.value} value={o.value} sx={{ gap: 0.75, '& svg': { fontSize: 18 } }}>
            {o.icon}
            {o.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    </Box>
  );
}

export function EmptyState({ icon, title, body, action }) {
  return (
    <Box
      sx={{
        textAlign: 'center', px: 3, py: { xs: 5, md: 7 },
        border: `2px dashed ${t.lineStrong}`, borderRadius: '20px', bgcolor: alphaSurface,
      }}
    >
      <Box
        sx={{
          width: 64, height: 64, borderRadius: '20px', mx: 'auto', mb: 2,
          display: 'grid', placeItems: 'center', bgcolor: t.brandSoft, color: t.brand, '& svg': { fontSize: 32 },
        }}
      >
        {icon}
      </Box>
      <Typography variant="h6" sx={{ mb: 0.5 }}>{title}</Typography>
      {body && <Typography color="text.secondary" sx={{ maxWidth: 440, mx: 'auto', mb: action ? 2.5 : 0 }}>{body}</Typography>}
      {action}
    </Box>
  );
}
const alphaSurface = 'rgba(255, 254, 252, 0.6)';

const STATUS = {
  draft: { label: 'Draft', fg: t.inkSoft, bg: t.surface2 },
  rendering: { label: 'Rendering', fg: t.blue, bg: t.blueSoft, pulse: true },
  completed: { label: 'Completed', fg: t.green, bg: t.greenSoft },
  failed: { label: 'Failed', fg: t.red, bg: t.redSoft },
  failed_quality: { label: 'Quality check failed', fg: t.amber, bg: t.amberSoft },
  cancelled: { label: 'Cancelled', fg: t.inkSoft, bg: t.surface2 },
};

export function StatusChip({ status }) {
  const s = STATUS[status] || { label: status || 'unknown', fg: t.inkSoft, bg: t.surface2 };
  return (
    <Box
      component="span"
      sx={{
        display: 'inline-flex', alignItems: 'center', gap: 0.85, px: 1.25, py: 0.4,
        borderRadius: '999px', bgcolor: s.bg, color: s.fg, fontSize: 12, fontWeight: 750, whiteSpace: 'nowrap',
      }}
    >
      <Box
        component="span"
        sx={{
          width: 7, height: 7, borderRadius: '50%', bgcolor: s.fg,
          animation: s.pulse ? 'pulse 1.2s ease-in-out infinite' : 'none',
        }}
      />
      {s.label}
    </Box>
  );
}

export function Stat({ icon, label, value, hint, tone = 'brand' }) {
  const tones = {
    brand: [t.brandSoft, t.brandDark],
    teal: [t.tealSoft, t.teal],
    blue: [t.blueSoft, t.blue],
  };
  const [bg, fg] = tones[tone] || tones.brand;
  return (
    <Paper sx={{ borderRadius: '18px', p: 2, display: 'flex', alignItems: 'center', gap: 1.75, boxShadow: t.shadow }}>
      <Box sx={{ width: 44, height: 44, borderRadius: '14px', display: 'grid', placeItems: 'center', bgcolor: bg, color: fg, flexShrink: 0 }}>
        {icon}
      </Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1, letterSpacing: '-0.02em' }}>{value}</Typography>
        <Typography variant="body2" color="text.secondary" noWrap>{label}{hint ? ` · ${hint}` : ''}</Typography>
      </Box>
    </Paper>
  );
}
