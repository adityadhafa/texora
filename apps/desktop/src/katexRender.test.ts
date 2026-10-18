import katex from 'katex';
import { describe, expect, it } from 'vitest';

/**
 * The authoritative KaTeX render check (design §B.6, AC-5 UI side): the real pinned katex
 * must render the valid fixture/golden LaTeX with no ParseError, and must throw on invalid
 * input. This is the ground truth the engine's allow-list pre-filter defers to.
 */
describe('real KaTeX render', () => {
  const valid = [
    '\\frac{a}{b}',
    'x^2 + y^2 = z^2',
    '\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}',
    '\\alpha + \\beta = \\gamma',
    '\\begin{matrix} a & b \\\\ c & d \\end{matrix}',
  ];

  it.each(valid)('renders valid LaTeX without ParseError: %s', (latex) => {
    expect(() => katex.renderToString(latex, { throwOnError: true })).not.toThrow();
  });

  const invalid = ['\\frac{a}{b', '\\begin{matrix} a \\end{bmatrix}', '\\notarealcommand{x}'];

  it.each(invalid)('throws ParseError on invalid LaTeX: %s', (latex) => {
    expect(() => katex.renderToString(latex, { throwOnError: true })).toThrow();
  });
});
