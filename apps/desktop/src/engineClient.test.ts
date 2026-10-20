import { afterEach, describe, expect, it, vi } from 'vitest';

import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

import { open as openDialog, save as saveDialog } from '@tauri-apps/plugin-dialog';

import {
  cancelJob,
  createJob,
  getEngineStatus,
  getHardware,
  getJob,
  getJobMarkdown,
  modelDownload,
  modelStatus,
  parseJobView,
  pickPdf,
  recognizeSnip,
  saveMarkdown,
  setDevice,
  subscribeEngineStatus,
  subscribeJobEvents,
  subscribeModelProgress,
  subscribeSnipCaptured,
  type EngineStatus,
  type JobView,
} from './engineClient';

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}));
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(),
}));
vi.mock('@tauri-apps/plugin-dialog', () => ({
  open: vi.fn(),
  save: vi.fn(),
}));

const invokeMock = vi.mocked(invoke);
const listenMock = vi.mocked(listen);
const openMock = vi.mocked(openDialog);
const saveMock = vi.mocked(saveDialog);

/** Raw JobView JSON as the Rust proxy returns it (engine snake_case). */
function rawJobViewJson(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    id: 'job-1',
    source_name: 'paper.pdf',
    source_path: '/docs/paper.pdf',
    status: 'running',
    total_pages: 10,
    priority: 0,
    error: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:01Z',
    progress: {
      total: 10,
      pending: 7,
      leased: 1,
      done: 2,
      failed: 0,
      needs_review: 1,
      pages_per_min: 12.5,
      eta_seconds: 42.0,
      ...(overrides.progress as Record<string, unknown> | undefined),
    },
    ...overrides,
  });
}

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

describe('parseJobView', () => {
  it('maps every snake_case field to the camelCase mirror', () => {
    const job: JobView = parseJobView(rawJobViewJson());
    expect(job.id).toBe('job-1');
    expect(job.sourceName).toBe('paper.pdf');
    expect(job.sourcePath).toBe('/docs/paper.pdf');
    expect(job.status).toBe('running');
    expect(job.totalPages).toBe(10);
    expect(job.progress.needsReview).toBe(1);
    expect(job.progress.pagesPerMin).toBe(12.5);
    expect(job.progress.etaSeconds).toBe(42);
  });

  it('tolerates a minimal failed poll payload (zeroed progress)', () => {
    const job = parseJobView(JSON.stringify({ id: 'job-9', status: 'failed', error: 'boom' }));
    expect(job.status).toBe('failed');
    expect(job.error).toBe('boom');
    expect(job.progress.total).toBe(0);
    expect(job.progress.pagesPerMin).toBeNull();
  });
});

describe('createJob', () => {
  it('invokes job_create with the serialized snake_case options body', async () => {
    invokeMock.mockResolvedValueOnce(rawJobViewJson());
    const job = await createJob('/docs/paper.pdf');
    expect(invokeMock).toHaveBeenCalledWith('job_create', {
      path: '/docs/paper.pdf',
      optionsJson: JSON.stringify({ formats: ['md'] }),
      priority: 0,
    });
    expect(job.id).toBe('job-1');
  });

  it('serializes page range fields to snake_case', async () => {
    invokeMock.mockResolvedValueOnce(rawJobViewJson());
    await createJob('/docs/paper.pdf', { formats: ['md'], pageStart: 0, pageEnd: 4, dpi: 200 }, 5);
    expect(invokeMock).toHaveBeenCalledWith('job_create', {
      path: '/docs/paper.pdf',
      optionsJson: JSON.stringify({ formats: ['md'], dpi: 200, page_start: 0, page_end: 4 }),
      priority: 5,
    });
  });
});

describe('getJob / cancelJob / getJobMarkdown', () => {
  it('getJob invokes job_get with the id', async () => {
    invokeMock.mockResolvedValueOnce(rawJobViewJson());
    const job = await getJob('job-1');
    expect(invokeMock).toHaveBeenCalledWith('job_get', { id: 'job-1' });
    expect(job.id).toBe('job-1');
  });

  it('cancelJob invokes job_cancel with the id', async () => {
    invokeMock.mockResolvedValueOnce(rawJobViewJson({ status: 'canceled' }));
    const job = await cancelJob('job-1');
    expect(invokeMock).toHaveBeenCalledWith('job_cancel', { id: 'job-1' });
    expect(job.status).toBe('canceled');
  });

  it('getJobMarkdown invokes job_export with format md and returns the raw body', async () => {
    invokeMock.mockResolvedValueOnce('# Title\n\n$$a+b$$\n');
    const md = await getJobMarkdown('job-1');
    expect(invokeMock).toHaveBeenCalledWith('job_export', { id: 'job-1', format: 'md' });
    expect(md).toContain('$$a+b$$');
  });
});

describe('subscribeJobEvents', () => {
  it('listens on engine://job-progress and forwards a parsed JobView', async () => {
    const unlisten = vi.fn();
    let handler: ((e: { payload: string }) => void) | undefined;
    listenMock.mockImplementationOnce((_e, cb) => {
      handler = cb as (e: { payload: string }) => void;
      return Promise.resolve(unlisten);
    });
    const received: JobView[] = [];
    const returned = await subscribeJobEvents((j) => received.push(j));
    expect(listenMock).toHaveBeenCalledWith('engine://job-progress', expect.any(Function));
    expect(returned).toBe(unlisten);
    handler?.({ payload: rawJobViewJson({ status: 'done' }) });
    expect(received[0].status).toBe('done');
    expect(received[0].progress.done).toBe(2);
  });
});

describe('pickPdf / saveMarkdown', () => {
  it('pickPdf opens a single-file PDF dialog and returns the chosen path', async () => {
    openMock.mockResolvedValueOnce('/docs/paper.pdf');
    const path = await pickPdf();
    expect(openMock).toHaveBeenCalledWith({
      multiple: false,
      directory: false,
      filters: [{ name: 'PDF', extensions: ['pdf'] }],
    });
    expect(path).toBe('/docs/paper.pdf');
  });

  it('pickPdf returns null when the dialog is canceled', async () => {
    openMock.mockResolvedValueOnce(null);
    expect(await pickPdf()).toBeNull();
  });

  it('saveMarkdown writes via save_text and returns true when a path is chosen', async () => {
    saveMock.mockResolvedValueOnce('/out/paper.md');
    invokeMock.mockResolvedValueOnce(undefined);
    const ok = await saveMarkdown('paper.md', '# hello');
    expect(saveMock).toHaveBeenCalledWith({
      defaultPath: 'paper.md',
      filters: [{ name: 'Markdown', extensions: ['md'] }],
    });
    expect(invokeMock).toHaveBeenCalledWith('save_text', {
      path: '/out/paper.md',
      contents: '# hello',
    });
    expect(ok).toBe(true);
  });

  it('saveMarkdown returns false (no write) when the dialog is canceled', async () => {
    saveMock.mockResolvedValueOnce(null);
    const ok = await saveMarkdown('paper.md', '# hello');
    expect(ok).toBe(false);
    expect(invokeMock).not.toHaveBeenCalled();
  });
});
