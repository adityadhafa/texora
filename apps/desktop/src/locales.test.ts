import { describe, expect, it } from 'vitest';

import en from './locales/en.json';
import id from './locales/id.json';

/** Recursively flatten a nested object into dotted key paths. */
function flattenKeys(obj: unknown, prefix = ''): string[] {
  if (obj === null || typeof obj !== 'object') return [prefix];
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) => {
    const path = prefix ? `${prefix}.${k}` : k;
    return flattenKeys(v, path);
  });
}

describe('i18n locale parity', () => {
  it('id.json and en.json have identical key sets', () => {
    const idKeys = new Set(flattenKeys(id));
    const enKeys = new Set(flattenKeys(en));

    const missingInEn = [...idKeys].filter((k) => !enKeys.has(k));
    const missingInId = [...enKeys].filter((k) => !idKeys.has(k));

    expect(missingInEn, `keys missing in en.json: ${missingInEn.join(', ')}`).toEqual([]);
    expect(missingInId, `keys missing in id.json: ${missingInId.join(', ')}`).toEqual([]);
  });

  it('includes the M2 snip + hardware keys', () => {
    const idKeys = new Set(flattenKeys(id));
    for (const key of [
      'snip.title',
      'snip.copyLatex',
      'snip.copyMathml',
      'snip.copyMarkdown',
      'snip.confidenceUnavailable',
      'snip.status.needsReview',
      'hardware.cpuSlowNote',
      'hardware.deviceCuda',
    ]) {
      expect(idKeys.has(key), `missing ${key}`).toBe(true);
    }
    // OMML copy is deferred to M6 — must NOT be present in M2.
    expect(idKeys.has('snip.copyOmml')).toBe(false);
  });
});
