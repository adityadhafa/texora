import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

import EngineStatusBadge from './EngineStatusBadge';
import type { EngineStatus } from './engineClient';
import './i18n';

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}));
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(),
}));

const invokeMock = vi.mocked(invoke);
const listenMock = vi.mocked(listen);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('EngineStatusBadge', () => {
  it('renders the initial status from engine_status', async () => {
    invokeMock.mockResolvedValueOnce({ state: 'healthy', port: 1234 } satisfies EngineStatus);
    listenMock.mockResolvedValueOnce(() => {});

    render(<EngineStatusBadge />);

    // Indonesian (default) label for `healthy` is "Siap".
    await waitFor(() => {
      expect(screen.getByText('Siap')).toBeTruthy();
    });
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('updates when an engine://status event arrives', async () => {
    invokeMock.mockResolvedValueOnce({ state: 'starting' } satisfies EngineStatus);
    let handler: ((event: { payload: EngineStatus }) => void) | undefined;
    listenMock.mockImplementationOnce((_event, cb) => {
      handler = cb as (event: { payload: EngineStatus }) => void;
      return Promise.resolve(() => {});
    });

    render(<EngineStatusBadge />);

    await waitFor(() => {
      expect(screen.getByText('Memulai')).toBeTruthy();
    });

    handler?.({ payload: { state: 'restarting', detail: 'engine exited' } });

    await waitFor(() => {
      expect(screen.getByText('Memulai ulang')).toBeTruthy();
    });
  });
});
