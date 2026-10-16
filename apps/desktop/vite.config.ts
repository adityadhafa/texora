/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Tauri-friendly Vite config: fixed dev port, no screen clearing so Tauri logs
// stay visible, and a predictable build target. The dev server itself is only
// ever started manually (never via automation) per the project tooling rules.
const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [react()],
  // Prevent Vite from obscuring Rust/Tauri errors in the terminal.
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
  },
  build: {
    // Modern Edge WebView2 (Windows) / WKWebView (macOS) / WebKitGTK (Linux).
    target: 'esnext',
    sourcemap: true,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
});
