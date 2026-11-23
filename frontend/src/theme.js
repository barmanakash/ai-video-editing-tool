import { alpha, createTheme } from '@mui/material/styles';

// Design tokens: a warm-white, paper-like palette with one confident terracotta accent.
export const t = {
  bg: '#FBF8F3',          // page: warm white
  sidebar: '#F6F1E8',
  surface: '#FFFEFC',     // cards
  surface2: '#F4EEE4',    // insets / hover
  line: '#E8DFD0',
  lineStrong: '#D8CCB8',
  ink: '#2A251F',
  inkSoft: '#6C6357',
  inkFaint: '#9C9283',
  brand: '#D9532C',
  brandDark: '#B4401E',
  brandSoft: '#FCEAE2',
  green: '#2F8A5F',
  greenSoft: '#E2F2E9',
  amber: '#B7791F',
  amberSoft: '#FBF0D8',
  red: '#C0392B',
  redSoft: '#FBE6E2',
  blue: '#2F6AA3',
  blueSoft: '#E3EEF8',
  teal: '#1E7A6C',
  tealSoft: '#DDF0EC',
  shadow: '0 1px 2px rgba(74, 52, 20, 0.06), 0 8px 24px -14px rgba(74, 52, 20, 0.20)',
  shadowLift: '0 2px 4px rgba(74, 52, 20, 0.08), 0 18px 34px -16px rgba(74, 52, 20, 0.32)',
};

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: t.brand, dark: t.brandDark, light: '#EE7A55', contrastText: '#ffffff' },
    secondary: { main: t.teal },
    success: { main: t.green },
    warning: { main: t.amber },
    error: { main: t.red },
    info: { main: t.blue },
    background: { default: t.bg, paper: t.surface },
    text: { primary: t.ink, secondary: t.inkSoft, disabled: t.inkFaint },
    divider: t.line,
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, Roboto, sans-serif',
    h4: { fontWeight: 800, letterSpacing: '-0.025em', lineHeight: 1.15 },
    h5: { fontWeight: 750, letterSpacing: '-0.02em' },
    h6: { fontWeight: 700, letterSpacing: '-0.01em' },
    subtitle1: { fontWeight: 650 },
    subtitle2: { fontWeight: 650 },
    button: { textTransform: 'none', fontWeight: 650 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        html: { colorScheme: 'light' },
        body: {
          backgroundColor: t.bg,
          backgroundImage: `radial-gradient(1100px 480px at 88% -12%, ${alpha(t.brand, 0.08)}, transparent 62%)`,
          backgroundAttachment: 'fixed',
        },
        '::selection': { background: alpha(t.brand, 0.22) },
        '*::-webkit-scrollbar': { width: 10, height: 10 },
        '*::-webkit-scrollbar-thumb': { background: t.lineStrong, borderRadius: 10, border: `2px solid ${t.bg}` },
        '@keyframes fadeUp': {
          from: { opacity: 0, transform: 'translateY(8px)' },
          to: { opacity: 1, transform: 'none' },
        },
        '@keyframes pulse': { '0%, 100%': { opacity: 1 }, '50%': { opacity: 0.3 } },
      },
    },
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: { root: { backgroundImage: 'none', border: `1px solid ${t.line}` } },
    },
    MuiMenu: { styleOverrides: { paper: { boxShadow: t.shadowLift, marginTop: 4, borderRadius: 12 } } },
    MuiAutocomplete: { styleOverrides: { paper: { boxShadow: t.shadowLift, borderRadius: 12 } } },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 11, fontWeight: 650, padding: '8px 18px' },
        sizeSmall: { padding: '4px 12px', borderRadius: 9 },
        sizeLarge: { padding: '12px 26px', fontSize: '1rem' },
        containedPrimary: {
          boxShadow: `0 1px 0 ${alpha('#ffffff', 0.25)} inset, 0 10px 20px -10px ${alpha(t.brand, 0.75)}`,
          '&:hover': { backgroundColor: t.brandDark },
        },
        outlinedInherit: {
          borderColor: t.lineStrong,
          backgroundColor: t.surface,
          '&:hover': { borderColor: t.inkFaint, backgroundColor: t.surface2 },
        },
        textInherit: { '&:hover': { backgroundColor: alpha(t.ink, 0.05) } },
      },
    },
    MuiIconButton: { styleOverrides: { root: { borderRadius: 10 } } },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: 8, fontWeight: 650 },
        sizeSmall: { height: 24 },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 11,
          backgroundColor: t.surface,
          '& .MuiOutlinedInput-notchedOutline': { borderColor: t.line },
          '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: t.lineStrong },
          '&.Mui-focused .MuiOutlinedInput-notchedOutline': { borderColor: t.brand, borderWidth: 1.5 },
          '&.Mui-focused': { boxShadow: `0 0 0 4px ${alpha(t.brand, 0.12)}` },
        },
      },
    },
    MuiInputLabel: { styleOverrides: { root: { '&.Mui-focused': { color: t.brandDark } } } },
    MuiToggleButtonGroup: {
      styleOverrides: {
        root: { backgroundColor: t.surface2, padding: 4, borderRadius: 13, gap: 4, border: `1px solid ${t.line}` },
        grouped: {
          border: '0 !important',
          margin: '0 !important',
          borderRadius: '9px !important',
        },
      },
    },
    MuiToggleButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 650,
          color: t.inkSoft,
          padding: '6px 14px',
          '&:hover': { backgroundColor: alpha(t.ink, 0.05) },
          '&.Mui-selected': {
            backgroundColor: t.surface,
            color: t.brandDark,
            boxShadow: `0 1px 2px rgba(74,52,20,0.14), 0 0 0 1px ${t.line}`,
            '&:hover': { backgroundColor: t.surface },
          },
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 12, alignItems: 'center' },
        standardInfo: { backgroundColor: t.blueSoft, color: t.ink, '& .MuiAlert-icon': { color: t.blue } },
        standardSuccess: { backgroundColor: t.greenSoft, color: t.ink, '& .MuiAlert-icon': { color: t.green } },
        standardWarning: { backgroundColor: t.amberSoft, color: t.ink, '& .MuiAlert-icon': { color: t.amber } },
        standardError: { backgroundColor: t.redSoft, color: t.ink, '& .MuiAlert-icon': { color: t.red } },
        outlinedInfo: { borderColor: t.line, backgroundColor: t.surface, color: t.inkSoft, '& .MuiAlert-icon': { color: t.blue } },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { height: 8, borderRadius: 8, backgroundColor: t.surface2 },
        bar: { borderRadius: 8 },
      },
    },
    MuiSlider: {
      styleOverrides: {
        root: { height: 6 },
        rail: { backgroundColor: t.lineStrong, opacity: 1 },
        thumb: { width: 18, height: 18, border: '3px solid #fff', boxShadow: '0 1px 5px rgba(0,0,0,0.25)' },
        markLabel: { fontSize: 11, color: t.inkFaint },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: { backgroundColor: t.ink, borderRadius: 8, fontSize: 12, padding: '6px 10px' },
        arrow: { color: t.ink },
      },
    },
    MuiAccordion: {
      styleOverrides: { root: { '&:before': { display: 'none' }, borderRadius: 12, overflow: 'hidden' } },
    },
    MuiDivider: { styleOverrides: { root: { borderColor: t.line } } },
  },
});

export default theme;
