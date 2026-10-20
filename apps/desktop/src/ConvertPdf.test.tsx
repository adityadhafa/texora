import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ConvertPdf from './ConvertPdf';
import {
  cancelJob,
  createJob,
  getJobMarkdown,
  pickPdf,
  saveMarkdown,
  subscribeJobEvents,
  type JobView,
} from './engineClient';
import './i18n';

// The view talks only to the typed client; mock it wholesale so no Tauri bridge is needed.
vi.mock('./engineClient', () => ({
  pickPdf: vi.fn(),
  createJob: vi.fn(),
  cancelJob: vi.fn(),
  getJobMarkdown: vi.fn(),
  saveMarkdown: vi.fn(),
  subscribeJobEvents: vi.fn(),
}));

const pickPdfMock = vi.mocked(pickPdf);
const createJobMock = vi.mocked(createJob);
const cancelJobMock = vi.mocked(cancelJob);
const getJobMarkdownMock = vi.mocked(getJobMarkdown);
const saveMarkdownMock = vi.mocked(saveMarkdown);
const subscribeJobEventsMock = vi.mocked(subscribeJobEvents);

/** Capture the progress callback registered by subscribeJobEvents so tests can drive it. */
let emitProgress: ((job: JobView) => void) | undefined;

function makeJob(overrides: Partial<JobView> = {}): JobView {
  return {
    id: 'job-1',
    sourceName: 'paper.pdf',
    sourcePath: '/docs/paper.pdf',
    status: 'running',
    totalPages: 10,
    priority: 0,
    error: null,
    createdAt: '',
    updatedAt: '',
    progress: {
      total: 10,
      pending: 7,
      leased: 1,
      done: 2,
      failed: 0,
      needsReview: 0,
      pagesPerMin: null,
      etaSeconds: null,
    },
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  emitProgress = undefined;
  subscribeJobEventsMock.mockImplementation((cb) => {
    emitProgress = cb;
    return Promise.resolve(() => {});
  });
  createJobMock.mockResolvedValue(makeJob());
});

afterEach(() => cleanup());

async function pickAndStart(): Promise<void> {
  pickPdfMock.mockResolvedValueOnce('/docs/paper.pdf');
  fireEvent.click(screen.getByRole('button', { name: /pilih pdf/i }));
  await screen.findByText('paper.pdf');
  fireEvent.click(screen.getByRole('button', { name: /mulai konversi/i }));
  await waitFor(() => expect(createJobMock).toHaveBeenCalled());
}

describe('ConvertPdf', () => {
  it('starts idle with a choose-PDF button and no file selected', () => {
    render(<ConvertPdf onBack={() => {}} />);
    expect(screen.getByRole('button', { name: /pilih pdf/i })).toBeTruthy();
    expect(screen.getByText(/belum ada pdf/i)).toBeTruthy();
  });

  it('shows the filename after picking a PDF', async () => {
    pickPdfMock.mockResolvedValueOnce('/docs/paper.pdf');
    render(<ConvertPdf onBack={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /pilih pdf/i }));
    expect(await screen.findByText('paper.pdf')).toBeTruthy();
    expect(screen.getByRole('button', { name: /mulai konversi/i })).toBeTruthy();
  });

  it('Start calls createJob and shows the running progress bar', async () => {
    render(<ConvertPdf onBack={() => {}} />);
    await pickAndStart();
    expect(createJobMock).toHaveBeenCalledWith('/docs/paper.pdf', { formats: ['md'] });
    expect(screen.getByRole('progressbar')).toBeTruthy();
  });

  it('a progress event drives the "page X of N" label', async () => {
    render(<ConvertPdf onBack={() => {}} />);
    await pickAndStart();
    emitProgress?.(makeJob({ progress: { ...makeJob().progress, done: 5, total: 10 } }));
    expect(await screen.findByText(/halaman 5 dari 10/i)).toBeTruthy();
  });

  it('Cancel calls cancelJob', async () => {
    cancelJobMock.mockResolvedValue(makeJob({ status: 'canceled' }));
    render(<ConvertPdf onBack={() => {}} />);
    await pickAndStart();
    fireEvent.click(screen.getByRole('button', { name: /batalkan/i }));
    await waitFor(() => expect(cancelJobMock).toHaveBeenCalledWith('job-1'));
  });

  it('a canceled poll event shows a neutral note, not the error alert', async () => {
    cancelJobMock.mockResolvedValue(makeJob({ status: 'canceled' }));
    render(<ConvertPdf onBack={() => {}} />);
    await pickAndStart();
    fireEvent.click(screen.getByRole('button', { name: /batalkan/i }));
    await waitFor(() => expect(cancelJobMock).toHaveBeenCalledWith('job-1'));

    // The engine's terminal 'canceled' status arrives via the poll bridge.
    emitProgress?.(makeJob({ status: 'canceled' }));

    // Neutral status note, never the red error alert.
    expect(await screen.findByText(/konversi dibatalkan/i)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('a terminal done event fetches + shows the markdown with Copy/Save wired', async () => {
    getJobMarkdownMock.mockResolvedValue('# Hello\n\n$$a+b$$\n');
    saveMarkdownMock.mockResolvedValue(true);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<ConvertPdf onBack={() => {}} />);
    await pickAndStart();
    emitProgress?.(makeJob({ status: 'done', progress: { ...makeJob().progress, done: 10 } }));

    const pre = await screen.findByTestId('convert-markdown');
    expect(pre.textContent).toContain('$$a+b$$');
    expect(getJobMarkdownMock).toHaveBeenCalledWith('job-1');

    fireEvent.click(screen.getByRole('button', { name: /salin markdown/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('# Hello\n\n$$a+b$$\n'));

    fireEvent.click(screen.getByRole('button', { name: /simpan \.md/i }));
    await waitFor(() => expect(saveMarkdownMock).toHaveBeenCalledWith('paper.md', expect.any(String)));
  });

  it('a failed event shows the error state', async () => {
    render(<ConvertPdf onBack={() => {}} />);
    await pickAndStart();
    emitProgress?.(makeJob({ status: 'failed', error: 'bad page' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
  });

  it('shows engine-not-ready when createJob throws a ProxyError', async () => {
    createJobMock.mockRejectedValueOnce({ kind: 'engineNotReady', message: 'not ready' });
    render(<ConvertPdf onBack={() => {}} />);
    await pickAndStart();
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText(/mesin belum siap/i)).toBeTruthy();
  });
});
