import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { SnipResult } from './engineClient';
import SnipPopup from './SnipPopup';
import './i18n';

afterEach(cleanup);

const okResult: SnipResult = {
  latex: '\\frac{a}{b}',
  confidence: 0,
  confidenceKind: 'unavailable',
  status: 'ok',
  validation: 'ok',
  mathml: '<math><mfrac><mi>a</mi><mi>b</mi></mfrac></math>',
  asciimath: null,
};

describe('SnipPopup', () => {
  it('renders the LaTeX and copy buttons from i18next', () => {
    render(<SnipPopup result={okResult} isDisplay onClose={() => {}} />);
    expect(screen.getByTestId('snip-latex').textContent).toBe('\\frac{a}{b}');
    // id is default: "Salin LaTeX".
    expect(screen.getByRole('button', { name: /salin latex/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /salin mathml/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /salin markdown/i })).toBeTruthy();
  });

  it('renders a real KaTeX preview for valid LaTeX', () => {
    render(<SnipPopup result={okResult} isDisplay onClose={() => {}} />);
    const preview = screen.getByTestId('snip-preview');
    // KaTeX emits a .katex root span.
    expect(preview.querySelector('.katex')).toBeTruthy();
  });

  it('shows the confidence-unavailable state', () => {
    render(<SnipPopup result={okResult} isDisplay onClose={() => {}} />);
    expect(screen.getByText(/keyakinan tidak tersedia/i)).toBeTruthy();
  });

  it('renders a could-not-recognize state for failed results, never fabricated LaTeX', () => {
    const failed: SnipResult = {
      latex: '',
      confidence: 0,
      confidenceKind: 'unavailable',
      status: 'failed',
      validation: 'failed',
      mathml: null,
      asciimath: null,
      detail: 'could not recognize',
    };
    render(<SnipPopup result={failed} isDisplay onClose={() => {}} />);
    expect(screen.queryByTestId('snip-latex')).toBeNull();
    // The failure detail message is shown (never fabricated LaTeX).
    expect(screen.getByText('could not recognize')).toBeTruthy();
  });

  it('copies Markdown with $$ wrapping for display math', () => {
    const copied: string[] = [];
    render(
      <SnipPopup result={okResult} isDisplay onClose={() => {}} onCopy={(t) => copied.push(t)} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /salin markdown/i }));
    expect(copied).toEqual(['$$\\frac{a}{b}$$']);
  });

  it('closes on Escape', () => {
    const onClose = vi.fn();
    render(<SnipPopup result={okResult} isDisplay onClose={onClose} />);
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
