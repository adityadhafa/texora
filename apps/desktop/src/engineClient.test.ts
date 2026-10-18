import { afterEach, describe, expect, it, vi } from 'vitest';

import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

import {
  getEngineStatus,
  getHardware,
  modelDownload,
  modelStatus,
  recognizeSnip,
  setDevice,
  subscribeEngineStatus,
  subscribeModelProgress,
  subscribeSnipCaptured,
  type EngineStatus,
} from './engineClient';

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

describe('recognizeSnip', () => {
  it('invokes recognize_snip and parses the snake_case engine JSON', async () => {
    invokeMock.mockResolvedValueOnce(
      JSON.stringify({
        latex: '\\frac{a}{b}',
        confidence: 0,
        confidence_kind: 'unavailable',
        status: 'ok',
        validation: 'ok',
        mathml: '<math></math>',
        asciimath: null,
        detail: null,
      }),
    );

    const result = await recognizeSnip('base64png', true);

    expect(invokeMock).toHaveBeenCalledWith('recognize_snip', {
      imageBase64: 'base64png',
      isDisplay: true,
    });
    expect(result.latex).toBe('\\frac{a}{b}');
    expect(result.confidenceKind).toBe('unavailable');
    expect(result.asciimath).toBeNull();
  });
});

describe('getHardware / setDevice', () => {
  it('getHardware invokes get_hardware and parses the result', async () => {
    invokeMock.mockResolvedValueOnce(JSON.stringify({ devices: ['cpu'], selected: 'cpu' }));
    const hw = await getHardware();
    expect(invokeMock).toHaveBeenCalledWith('get_hardware');
    expect(hw).toEqual({ devices: ['cpu'], selected: 'cpu' });
  });

  it('setDevice invokes set_device with the device', async () => {
    invokeMock.mockResolvedValueOnce(JSON.stringify({ devices: ['cpu', 'cuda'], selected: 'cuda' }));
    const hw = await setDevice('cuda');
    expect(invokeMock).toHaveBeenCalledWith('set_device', { device: 'cuda' });
    expect(hw.selected).toBe('cuda');
  });
});

describe('modelStatus / modelDownload', () => {
  it('modelStatus invokes model_status and maps camelCase fields', async () => {
    invokeMock.mockResolvedValueOnce(
      JSON.stringify({
        id: 'pix2tex',
        state: 'downloading',
        bytes_received: 10,
        bytes_total: 100,
        files: [{ name: 'weights.pth', received: 10, total: 100 }],
        detail: null,
      }),
    );
    const p = await modelStatus('pix2tex');
    expect(invokeMock).toHaveBeenCalledWith('model_status', { id: 'pix2tex' });
    expect(p.bytesReceived).toBe(10);
    expect(p.bytesTotal).toBe(100);
  });

  it('modelDownload invokes model_download', async () => {
    invokeMock.mockResolvedValueOnce(
      JSON.stringify({
        id: 'pix2tex',
        state: 'downloading',
        bytes_received: 0,
        bytes_total: 100,
        files: [],
      }),
    );
    const p = await modelDownload('pix2tex');
    expect(invokeMock).toHaveBeenCalledWith('model_download', { id: 'pix2tex' });
    expect(p.state).toBe('downloading');
  });
});

describe('event subscriptions', () => {
  it('subscribeSnipCaptured listens on engine://snip-captured', async () => {
    const unlisten = vi.fn();
    let handler: ((e: { payload: string }) => void) | undefined;
    listenMock.mockImplementationOnce((_e, cb) => {
      handler = cb as (e: { payload: string }) => void;
      return Promise.resolve(unlisten);
    });
    const received: string[] = [];
    await subscribeSnipCaptured((b64) => received.push(b64));
    expect(listenMock).toHaveBeenCalledWith('engine://snip-captured', expect.any(Function));
    handler?.({ payload: 'abc123' });
    expect(received).toEqual(['abc123']);
  });

  it('subscribeModelProgress listens on engine://model-progress and parses payloads', async () => {
    const unlisten = vi.fn();
    let handler: ((e: { payload: string }) => void) | undefined;
    listenMock.mockImplementationOnce((_e, cb) => {
      handler = cb as (e: { payload: string }) => void;
      return Promise.resolve(unlisten);
    });
    const received: Array<{ bytesReceived: number }> = [];
    await subscribeModelProgress((p) => received.push(p));
    expect(listenMock).toHaveBeenCalledWith('engine://model-progress', expect.any(Function));
    handler?.({
      payload: JSON.stringify({
        id: 'pix2tex',
        state: 'downloading',
        bytes_received: 42,
        bytes_total: 100,
        files: [],
      }),
    });
    expect(received[0].bytesReceived).toBe(42);
  });
});
