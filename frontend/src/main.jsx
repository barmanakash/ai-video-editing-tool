import React from 'react';
import { createRoot } from 'react-dom/client';
import { CssBaseline, ThemeProvider, createTheme } from '@mui/material';
import App from './App.jsx';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#7c6cff' },
    secondary: { main: '#2dd4bf' },
    background: { default: '#0f1115', paper: '#171a21' },
  },
  shape: { borderRadius: 10 },
  typography: { fontFamily: 'Inter, Roboto, "Segoe UI", sans-serif' },
});

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <App />
    </ThemeProvider>
  </React.StrictMode>
);
