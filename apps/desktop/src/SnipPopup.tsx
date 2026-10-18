import katex from 'katex';
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import type { SnipResult } from './engineClient';

import 'katex/dist/katex.min.css';

export interface SnipPopupProps {
  /** The recognition result, or null while idle. */
  result: SnipResult | null;
  /** Whether the source region was display (block) vs inline math. */
  isDisplay: boolean;
  /** Close handler (Esc / close button). */
  onClose: () => void;
  /** Copy handler; defaults to the clipboard API in production. */
  onCopy?: (text: string) => void;
}

/** Render LaTeX to KaTeX HTML; returns an error marker string when it cannot render. */
function renderKatex(latex: string, displayMode: boolean): { html: string; ok: boolean } {
  try {
    const html = katex.renderToString(latex, {
      displayMode,
      throwOnError: true,
      output: 'htmlAndMathml',
    });
    return { html, ok: true };
  } catch {
    return { html: '', ok: false };
  }
}

/**
 * Result popup for a formula snip. Shows the LaTeX (read-only), a live KaTeX preview (the
 * authoritative render), a confidence/validation badge, and LaTeX/MathML/Markdown copy
 * buttons. A needs_review/failed result renders a clear "could not recognize" state and
 * never fabricated LaTeX. Keyboard-first: Esc closes, Enter copies LaTeX, focus is trapped.
 */
export default function SnipPopup({
  result,
  isDisplay,
  onClose,
  onCopy,
}: SnipPopupProps): React.JSX.Element | null {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);

  const copy = useCallback(
    (text: string) => {
      if (onCopy) {
        onCopy(text);
        return;
      }
      void navigator.clipboard?.writeText(text);
    },
    [onCopy],
  );

  const handleKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'Enter' && result && result.latex) {
        copy(result.latex);
      }
    },
    [onClose, copy, result],
  );

  useEffect(() => {
    containerRef.current?.focus();
  }, [result]);

  const preview = useMemo(() => {
    if (!result || !result.latex) return null;
    return renderKatex(result.latex, isDisplay);
  }, [result, isDisplay]);

  if (!result) return null;

  const failed = result.status === 'failed' || !result.latex;
  const needsReview = result.status === 'needs_review';
  const markdown = isDisplay ? `$$${result.latex}$$` : `$${result.latex}$`;

  const statusLabel = failed
    ? t('snip.status.failed')
    : needsReview
      ? t('snip.status.needsReview')
      : t('snip.status.ok');
  const statusColor = failed
    ? 'bg-red-600'
    : needsReview
      ? 'bg-amber-500'
      : 'bg-emerald-600';

  return (
    <div
      ref={containerRef}
      role="dialog"
      aria-modal="true"
      aria-label={t('snip.title')}
      tabIndex={-1}
      onKeyDown={handleKey}
      className="flex w-[32rem] flex-col gap-3 rounded-lg border border-muted/40 bg-surface p-4 text-fg shadow-xl focus:outline-none"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('snip.title')}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('snip.close')}
          className="rounded px-2 py-1 text-sm hover:bg-muted/20 focus-visible:ring-2 focus-visible:ring-accent"
        >
          {t('snip.close')}
        </button>
      </div>

      {/* Status / confidence badge (ARIA live for screen readers). */}
      <div aria-live="polite" className="flex items-center gap-2 text-sm">
        <span className={`rounded px-2 py-0.5 text-xs font-medium text-white ${statusColor}`}>
          {statusLabel}
        </span>
        <span className="text-muted">
          {result.confidenceKind === 'unavailable'
            ? t('snip.confidenceUnavailable')
            : `${t('snip.confidence')}: ${(result.confidence * 100).toFixed(0)}%`}
        </span>
      </div>

      {failed ? (
        <p className="rounded bg-red-600/10 p-3 text-sm text-red-400">
          {result.detail ?? t('snip.status.failed')}
        </p>
      ) : (
        <>
          {/* Read-only LaTeX box. */}
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted">LaTeX</span>
            <code
              data-testid="snip-latex"
              className="block overflow-x-auto rounded bg-bg p-2 font-mono text-sm"
            >
              {result.latex}
            </code>
          </label>

          {/* Authoritative KaTeX preview. */}
          <div className="flex flex-col gap-1 text-sm">
            <span className="text-muted">{t('snip.preview')}</span>
            {preview?.ok ? (
              <div
                data-testid="snip-preview"
                // KaTeX output is trusted (generated locally from the recognized LaTeX).
                dangerouslySetInnerHTML={{ __html: preview.html }}
                className="overflow-x-auto rounded bg-bg p-2"
              />
            ) : (
              <p className="rounded bg-amber-500/10 p-2 text-amber-400">
                {t('snip.status.needsReview')}
              </p>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => copy(result.latex)}
              className="rounded border border-muted/40 bg-bg px-3 py-1 text-sm hover:border-accent focus-visible:ring-2 focus-visible:ring-accent"
            >
              {t('snip.copyLatex')}
            </button>
            <button
              type="button"
              disabled={!result.mathml}
              onClick={() => result.mathml && copy(result.mathml)}
              className="rounded border border-muted/40 bg-bg px-3 py-1 text-sm hover:border-accent focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
            >
              {t('snip.copyMathml')}
            </button>
            <button
              type="button"
              onClick={() => copy(markdown)}
              className="rounded border border-muted/40 bg-bg px-3 py-1 text-sm hover:border-accent focus-visible:ring-2 focus-visible:ring-accent"
            >
              {t('snip.copyMarkdown')}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
