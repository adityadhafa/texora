/**
 * Single typed client for the Texora engine.
 *
 * This is the ONLY module allowed to import `invoke`/`listen` from `@tauri-apps/api`. Every
 * component reaches the engine through the functions exported here so the UI never touches
 * the Tauri bridge directly, and it makes NO `fetch` — the engine port + bearer token stay
 * in Rust, reached via the authenticated proxy commands (see `.kiro/steering/*`).
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

/** Recognition/validation status — mirrors the engine `RecognitionStatus` StrEnum exactly. */
export type RecognitionStatus = 'ok' | 'needs_review' | 'failed';

/** How a confidence value was derived — mirrors the engine `ConfidenceKind`. */
export type ConfidenceKind = 'token_logprob' | 'unavailable';

/** Snip recognition result — mirrors the engine `SnipResponse`. */
export interface SnipResult {
  latex: string;
  confidence: number;
  confidenceKind: ConfidenceKind;
  status: RecognitionStatus;
  validation: RecognitionStatus;
  mathml: string | null;
  asciimath: string | null; // always null in M2 (M6 exporters)
  detail?: string | null;
}

/** Hardware report — mirrors the engine `HardwareResponse`. */
export interface Hardware {
  devices: string[];
  selected: string;
}

/** Model-download lifecycle state — mirrors the engine `ModelDownloadState`. */
export type ModelDownloadState = 'downloading' | 'verifying' | 'ready' | 'corrupt' | 'error';

/** Per-file download progress — mirrors the engine `ModelFileProgress`. */
export interface ModelFileProgress {
  name: string;
  received: number;
  total: number;
}

/** Model-download progress — mirrors the engine `ModelProgress`. */
export interface ModelProgress {
  id: string;
  state: ModelDownloadState;
  bytesReceived: number;
  bytesTotal: number;
  files: ModelFileProgress[];
  detail?: string | null;
}

/** Tauri command names. */
const STATUS_COMMAND = 'engine_status';
const RECOGNIZE_SNIP_COMMAND = 'recognize_snip';
const GET_HARDWARE_COMMAND = 'get_hardware';
const SET_DEVICE_COMMAND = 'set_device';
const MODEL_STATUS_COMMAND = 'model_status';
const MODEL_DOWNLOAD_COMMAND = 'model_download';

/** Tauri event names. */
const STATUS_EVENT = 'engine://status';
const SNIP_CAPTURED_EVENT = 'engine://snip-captured';
const MODEL_PROGRESS_EVENT = 'engine://model-progress';

/** Fetch the current engine status once. */
export function getEngineStatus(): Promise<EngineStatus> {
  return invoke<EngineStatus>(STATUS_COMMAND);
}

/** Subscribe to live engine status updates. */
export function subscribeEngineStatus(
  callback: (status: EngineStatus) => void,
): Promise<UnlistenFn> {
  return listen<EngineStatus>(STATUS_EVENT, (event) => {
    callback(event.payload);
  });
}

/**
 * The Rust proxy commands return the engine's JSON body as a string; parse it here so
 * callers get typed objects. snake_case engine fields are mapped to the camelCase TS mirror.
 */
interface RawSnip {
  latex: string;
  confidence: number;
  confidence_kind: ConfidenceKind;
  status: RecognitionStatus;
  validation: RecognitionStatus;
  mathml: string | null;
  asciimath: string | null;
  detail?: string | null;
}

function parseSnip(json: string): SnipResult {
  const raw = JSON.parse(json) as RawSnip;
  return {
    latex: raw.latex,
    confidence: raw.confidence,
    confidenceKind: raw.confidence_kind,
    status: raw.status,
    validation: raw.validation,
    mathml: raw.mathml,
    asciimath: raw.asciimath,
    detail: raw.detail,
  };
}

/** Recognize a captured PNG (base64) into LaTeX + MathML via the engine. */
export async function recognizeSnip(pngBase64: string, isDisplay: boolean): Promise<SnipResult> {
  const json = await invoke<string>(RECOGNIZE_SNIP_COMMAND, {
    imageBase64: pngBase64,
    isDisplay,
  });
  return parseSnip(json);
}

/** Report detected devices and the current selection. */
export async function getHardware(): Promise<Hardware> {
  const json = await invoke<string>(GET_HARDWARE_COMMAND);
  return JSON.parse(json) as Hardware;
}

/** Override the execution device; returns the updated hardware state. */
export async function setDevice(device: string): Promise<Hardware> {
  const json = await invoke<string>(SET_DEVICE_COMMAND, { device });
  return JSON.parse(json) as Hardware;
}

interface RawModelProgress {
  id: string;
  state: ModelDownloadState;
  bytes_received: number;
  bytes_total: number;
  files: ModelFileProgress[];
  detail?: string | null;
}

function parseModelProgress(json: string): ModelProgress {
  const raw = JSON.parse(json) as RawModelProgress;
  return {
    id: raw.id,
    state: raw.state,
    bytesReceived: raw.bytes_received,
    bytesTotal: raw.bytes_total,
    files: raw.files,
    detail: raw.detail,
  };
}

/** Get a model's current download/status snapshot. */
export async function modelStatus(id: string): Promise<ModelProgress> {
  const json = await invoke<string>(MODEL_STATUS_COMMAND, { id });
  return parseModelProgress(json);
}

/** Trigger a (non-blocking) model download; progress arrives via model-progress events. */
export async function modelDownload(id: string): Promise<ModelProgress> {
  const json = await invoke<string>(MODEL_DOWNLOAD_COMMAND, { id });
  return parseModelProgress(json);
}

/**
 * Subscribe to captured-snip events. The payload is the base64 PNG, or an `ERROR:<msg>`
 * string when capture failed in Rust.
 */
export function subscribeSnipCaptured(
  callback: (pngBase64OrError: string) => void,
): Promise<UnlistenFn> {
  return listen<string>(SNIP_CAPTURED_EVENT, (event) => {
    callback(event.payload);
  });
}

/** Subscribe to model-download progress events. */
export function subscribeModelProgress(
  callback: (progress: ModelProgress) => void,
): Promise<UnlistenFn> {
  return listen<string>(MODEL_PROGRESS_EVENT, (event) => {
    callback(parseModelProgress(event.payload));
  });
}
