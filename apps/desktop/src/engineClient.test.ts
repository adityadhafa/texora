import { afterEach, describe, expect, it, vi } from 'vitest';

import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

import { getEngineStatus, subscribeEngineStatus, type EngineStatus } from './engineClient';

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}));
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(),
}));

const invokeMock = vi.mocked(invoke);
const listenMock = vi.mocked(listen);

afterEach(() => {
  vi.clearAllMocks();
});

describe('getEngineStatus', () => {
  it('invokes the engine_status command and returns the status', async () => {
    const status: EngineStatus = { state: 'healthy', port: 54321 };
    invokeMock.mockResolvedValueOnce(status);

    const result = await getEngineStatus();

    expect(invokeMock).toHaveBeenCalledWith('engine_status');
    expect(result).toEqual(status);
  });
});

describe('subscribeEngineStatus', () => {
  it('listens on engine://status and forwards payloads to the callback', async () => {
    const unlisten = vi.fn();
    let handler: ((event: { payload: EngineStatus }) => void) | undefined;
    listenMock.mockImplementationOnce((_event, cb) => {
      handler = cb as (event: { payload: EngineStatus }) => void;
      return Promise.resolve(unlisten);
    });

    const received: EngineStatus[] = [];
    const returnedUnlisten = await subscribeEngineStatus((s) => received.push(s));

    expect(listenMock).toHaveBeenCalledWith('engine://status', expect.any(Function));
    expect(returnedUnlisten).toBe(unlisten);

    const payload: EngineStatus = { state: 'restarting', detail: 'engine exited' };
    handler?.({ payload });

    expect(received).toEqual([payload]);
  });
});
