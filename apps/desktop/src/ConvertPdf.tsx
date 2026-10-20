import { useCallback, useEffect, useReducer, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import {
  cancelJob,
  createJob,
  getJobMarkdown,
  pickPdf,
  saveMarkdown,
  subscribeJobEvents,
  type JobView,
} from './engineClient';

/**
 * Convert PDF → Markdown screen. This is Texora's headline feature wired end-to-end to the
 * engine job API through the single typed client (`engineClient`): pick a PDF, start a job,
 * watch live progress driven by the Rust `engine://job-progress` poll bridge, then fetch and
 * display the exported Markdown with Copy + Save.
 *
 * The component NEVER touches the Tauri bridge directly — every engine/dialog call goes
 * through `engineClient`. States are an explicit union so the UI stays honest: failed and
 * needs-review pages are surfaced from the engine's own counts, never hidden or fabricated.
 */

type Phase = 'idle' | 'selected' | 'running' | 'done' | 'failed';

interface State {
  phase: Phase;
  filePath: string | null;
  fileName: string | null;
  jobId: string | null;
  job: JobView | null;
  markdown: string | null;
  errorKey: string | null;
  copied: boolean;
  saved: boolean;
}

type Action =
  | { type: 'picked'; path: string; name: string }
  | { type: 'start'; jobId: string; job: JobView }
  | { type: 'progress'; job: JobView }
  | { type: 'exported'; markdown: string }
  | { type: 'failed'; errorKey: string; job?: JobView }
  | { type: 'copied' }
  | { type: 'saved' }
  | { type: 'reset' };

const initialState: State = {
  phase: 'idle',
  filePath: null,
  fileName: null,
  jobId: null,
  job: null,
  markdown: null,
  errorKey: null,
  copied: false,
  saved: false,
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'picked':
      return {
        ...initialState,
        phase: 'selected',
        filePath: action.path,
        fileName: action.name,
      };
    case 'start':
      return { ...state, phase: 'running', jobId: action.jobId, job: action.job, errorKey: null };
    case 'progress':
      return { ...state, job: action.job };
    case 'exported':
      return { ...state, phase: 'done', markdown: action.markdown };
    case 'failed':
      return { ...state, phase: 'failed', errorKey: action.errorKey, job: action.job ?? state.job };
    case 'copied':
      return { ...state, copied: true, saved: false };
    case 'saved':
      return { ...state, saved: true, copied: false };
    case 'reset':
      return initialState;
    default:
      return state;
  }
}

/** Extract the file name from an absolute path (cross-platform, no node deps). */
function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

/** Map a thrown engine error (ProxyError `{ kind }`) to a translation key. */
function errorKeyFor(err: unknown): string {
  if (err && typeof err === 'object' && 'kind' in err) {
    const kind = (err as { kind: unknown }).kind;
    if (kind === 'engineNotReady') return 'convert.error.engineNotReady';
  }
  return 'convert.error.generic';
}

const TERMINAL: ReadonlySet<string> = new Set(['done', 'failed', 'canceled']);

export interface ConvertPdfProps {
  onBack: () => void;
}

export default function ConvertPdf({ onBack }: ConvertPdfProps): React.JSX.Element {
  const { t } = useTranslation();
  const [state, dispatch] = useReducer(reducer, initialState);
  const unlistenRef = useRef<(() => void) | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  // Guard against double-handling the terminal transition from repeated poll frames.
  const finishedRef = useRef(false);

  const cleanup = useCallback(() => {
    if (unlistenRef.current) {
      unlistenRef.current();
      unlistenRef.current = null;
    }
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const onPick = useCallback(async () => {
    const path = await pickPdf();
    if (path) {
      dispatch({ type: 'picked', path, name: baseName(path) });
    }
  }, []);

  const handleTerminal = useCallback(
    async (job: JobView) => {
      if (finishedRef.current) return;
      finishedRef.current = true;
      cleanup();
      if (job.status === 'done') {
        try {
          const markdown = await getJobMarkdown(job.id);
          dispatch({ type: 'exported', markdown });
        } catch {
          dispatch({ type: 'failed', errorKey: 'convert.error.export', job });
        }
      } else {
        dispatch({ type: 'failed', errorKey: 'convert.error.generic', job });
      }
    },
    [cleanup],
  );

  const onStart = useCallback(async () => {
    if (!state.filePath) return;
    finishedRef.current = false;
    try {
      const unlisten = await subscribeJobEvents((job) => {
        dispatch({ type: 'progress', job });
        if (TERMINAL.has(job.status)) {
          void handleTerminal(job);
        }
      });
      unlistenRef.current = unlisten;
      const job = await createJob(state.filePath, { formats: ['md'] });
      dispatch({ type: 'start', jobId: job.id, job });
    } catch (err) {
      cleanup();
      dispatch({ type: 'failed', errorKey: errorKeyFor(err) });
    }
  }, [state.filePath, handleTerminal, cleanup]);

  const onCancel = useCallback(async () => {
    if (!state.jobId) return;
    try {
      await cancelJob(state.jobId);
    } catch {
      // The poll bridge still reports the terminal state; ignore a cancel race here.
    }
  }, [state.jobId]);

  const onCopy = useCallback(async () => {
    if (!state.markdown) return;
    await navigator.clipboard?.writeText(state.markdown);
    dispatch({ type: 'copied' });
  }, [state.markdown]);

  const onSave = useCallback(async () => {
    if (!state.markdown) return;
    const defaultName = (state.fileName ?? 'document.pdf').replace(/\.pdf$/i, '.md');
    const ok = await saveMarkdown(defaultName, state.markdown);
    if (ok) dispatch({ type: 'saved' });
  }, [state.markdown, state.fileName]);

  // Move focus to the result panel once the Markdown is shown (accessibility).
  useEffect(() => {
    if (state.phase === 'done') {
      resultRef.current?.focus();
    }
  }, [state.phase]);

  const progress = state.job?.progress;
  const total = progress?.total ?? state.job?.totalPages ?? 0;
  const done = progress?.done ?? 0;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const statusKey = state.job ? `convert.status.${state.job.status}` : 'convert.status.queued';

  const buttonClass =
    'rounded-md border border-muted/40 bg-surface px-4 py-2 text-sm font-medium text-fg transition-colors hover:border-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50';
  const primaryClass =
    'rounded-md border border-accent bg-accent/10 px-4 py-2 text-sm font-medium text-fg transition-colors hover:bg-accent/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50';

  return (
    <main className="mx-auto flex h-full w-full max-w-3xl flex-col gap-5 overflow-y-auto bg-bg p-6 text-fg">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">{t('convert.title')}</h1>
        <button type="button" onClick={onBack} className={buttonClass} aria-label={t('convert.back')}>
          {t('convert.back')}
        </button>
      </div>
      <p className="text-sm text-muted">{t('convert.intro')}</p>

      {/* File picking */}
      <section className="flex flex-col gap-3 rounded-lg border border-muted/40 bg-surface p-4">
        {state.fileName ? (
          <p className="text-sm">
            <span className="text-muted">{t('convert.selectedFile')}: </span>
            <span className="font-mono">{state.fileName}</span>
          </p>
        ) : (
          <p className="text-sm text-muted">{t('convert.noFile')}</p>
        )}

        <div className="flex flex-wrap gap-2">
          {state.phase === 'idle' || state.phase === 'selected' ? (
            <button type="button" onClick={onPick} className={buttonClass}>
              {state.fileName ? t('convert.chooseDifferent') : t('convert.open')}
            </button>
          ) : null}
          {state.phase === 'selected' ? (
            <button type="button" onClick={onStart} className={primaryClass}>
              {t('convert.start')}
            </button>
          ) : null}
          {state.phase === 'running' ? (
            <button type="button" onClick={onCancel} className={buttonClass}>
              {t('convert.cancel')}
            </button>
          ) : null}
          {(state.phase === 'done' || state.phase === 'failed') && (
            <button type="button" onClick={() => dispatch({ type: 'reset' })} className={buttonClass}>
              {t('convert.open')}
            </button>
          )}
        </div>
      </section>

      {/* Progress */}
      {state.phase === 'running' || state.phase === 'done' || state.phase === 'failed' ? (
        <section className="flex flex-col gap-2 rounded-lg border border-muted/40 bg-surface p-4">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium" aria-live="polite">
              {t(statusKey)}
            </span>
            {total > 0 ? (
              <span className="text-muted">
                {t('convert.pageProgress', { done, total })}
              </span>
            ) : null}
          </div>
          <div
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={t('convert.title')}
            className="h-2 w-full overflow-hidden rounded bg-muted/20"
          >
            <div
              className="h-full rounded bg-accent transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          {progress ? (
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              {progress.pagesPerMin != null ? (
                <span>{t('convert.pagesPerMin', { rate: progress.pagesPerMin.toFixed(1) })}</span>
              ) : null}
              {progress.etaSeconds != null ? (
                <span>{t('convert.eta', { seconds: Math.round(progress.etaSeconds) })}</span>
              ) : null}
              {progress.needsReview > 0 ? (
                <span className="text-amber-400">
                  {t('convert.needsReview', { count: progress.needsReview })}
                </span>
              ) : null}
              {progress.failed > 0 ? (
                <span className="text-red-400">
                  {t('convert.failedPages', { count: progress.failed })}
                </span>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}

      {/* Error */}
      {state.phase === 'failed' ? (
        <p className="rounded-lg bg-red-600/10 p-3 text-sm text-red-400" role="alert">
          {state.errorKey ? t(state.errorKey) : t('convert.error.generic')}
          {state.job?.error ? ` (${state.job.error})` : ''}
        </p>
      ) : null}

      {/* Result */}
      {state.phase === 'done' && state.markdown != null ? (
        <section
          ref={resultRef}
          tabIndex={-1}
          className="flex flex-col gap-3 rounded-lg border border-muted/40 bg-surface p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          aria-label={t('convert.result.title')}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">{t('convert.result.title')}</h2>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={onCopy} className={buttonClass}>
                {state.copied ? t('convert.copied') : t('convert.copyMarkdown')}
              </button>
              <button type="button" onClick={onSave} className={buttonClass}>
                {state.saved ? t('convert.saved') : t('convert.saveMd')}
              </button>
            </div>
          </div>
          <pre
            data-testid="convert-markdown"
            className="max-h-[32rem] overflow-auto rounded bg-bg p-3 font-mono text-sm whitespace-pre-wrap break-words"
          >
            {state.markdown}
          </pre>
        </section>
      ) : null}
    </main>
  );
}
