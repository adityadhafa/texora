import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

// vitest runs with cwd = the desktop package dir; the sources live under ./src.
function resolveSrcDir(): string {
  const cwd = process.cwd();
  const direct = join(cwd, 'src');
  if (existsSync(join(direct, 'engineClient.ts'))) return direct;
  // Fall back to the repo-root-relative path when run from the workspace root.
  return join(cwd, 'apps', 'desktop', 'src');
}

const SRC_DIR = resolveSrcDir();

/** Recursively list production .ts/.tsx files (excluding test files). */
function productionSources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...productionSources(full));
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry)) continue;
    if (/\.test\.(ts|tsx)$/.test(entry)) continue;
    out.push(full);
  }
  return out;
}

describe('engine bridge invariant', () => {
  const files = productionSources(SRC_DIR);

  it('only engineClient.ts imports invoke/listen from @tauri-apps/api', () => {
    const offenders = files.filter((f) => {
      if (f.endsWith('engineClient.ts')) return false;
      const text = readFileSync(f, 'utf-8');
      return /from '@tauri-apps\/api/.test(text);
    });
    expect(offenders, `files importing the Tauri bridge directly: ${offenders.join(', ')}`).toEqual(
      [],
    );
  });

  it('no production module uses fetch() for engine access', () => {
    const offenders = files.filter((f) => {
      const text = readFileSync(f, 'utf-8');
      // Word-boundary fetch( call (not "prefetch"/comments about fetch).
      return /\bfetch\s*\(/.test(text);
    });
    expect(offenders, `files calling fetch(): ${offenders.join(', ')}`).toEqual([]);
  });
});
