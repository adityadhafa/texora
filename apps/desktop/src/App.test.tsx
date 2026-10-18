import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import './i18n';

// App renders the live engine status badge + hardware settings, which call the typed client.
// Mock the Tauri bridge so the component mounts without a running backend. `engine_status`
// returns a status object; the proxy commands return JSON strings (as the Rust proxy does).
vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn((command: string) => {
    if (command === 'engine_status') return Promise.resolve({ state: 'starting' });
    if (command === 'get_hardware')
      return Promise.resolve(JSON.stringify({ devices: ['cpu'], selected: 'cpu' }));
    return Promise.resolve('{}');
  }),
}));
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
}));

afterEach(() => {
  cleanup();
  document.documentElement.classList.remove('dark');
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe('App', () => {
  it('renders the Texora home heading', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: 'Texora' })).toBeTruthy();
  });

  it('toggles the theme class on the document root', () => {
    render(<App />);
    // Default language is Indonesian ("Ubah tema"); match the i18n label.
    const toggle = screen.getByRole('button', { name: /ubah tema/i });
    const wasDark = document.documentElement.classList.contains('dark');

    fireEvent.click(toggle);

    expect(document.documentElement.classList.contains('dark')).toBe(!wasDark);
  });
});
