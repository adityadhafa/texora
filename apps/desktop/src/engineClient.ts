/**
 * Single typed client for the Texora engine.
 *
 * This is the ONLY module allowed to import `invoke`/`listen` from
 * `@tauri-apps/api`. Every component reads engine status through the functions
 * exported here so the UI never touches the Tauri bridge directly (see
 * `.kiro/steering/coding-standards.md`).
 */
import { invoke } from '@tauri-apps/api/core';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';

/** Lifecycle state reported by the Rust supervisor (`EngineState`). */
export type EngineState = 'starting' | 'healthy' | 'unhealthy' | 'restarting' | 'stopped';

/** Typed status payload mirroring the Rust `EngineStatus` struct. */
export interface EngineStatus {
  state: EngineState;
  port?: number;
  detail?: string;
}

/** Tauri command name backing {@link getEngineStatus}. */
const STATUS_COMMAND = 'engine_status';

/** Tauri event name backing {@link subscribeEngineStatus}. */
const STATUS_EVENT = 'engine://status';

/** Fetch the current engine status once. */
export function getEngineStatus(): Promise<EngineStatus> {
  return invoke<EngineStatus>(STATUS_COMMAND);
}

/**
 * Subscribe to live engine status updates.
 *
 * @param callback invoked with each new status as the supervisor transitions.
 * @returns a promise resolving to an unsubscribe function.
 */
export function subscribeEngineStatus(
  callback: (status: EngineStatus) => void,
): Promise<UnlistenFn> {
  return listen<EngineStatus>(STATUS_EVENT, (event) => {
    callback(event.payload);
  });
}
