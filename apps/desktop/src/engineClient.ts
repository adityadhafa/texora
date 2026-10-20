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
import { open as openDialog, save as saveDialog } from '@tauri-apps/plugin-dialog';

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

// --- PDF → Markdown jobs ---------------------------------------------------------------------

/** Job lifecycle status — mirrors the engine's active + terminal job statuses exactly. */
export type JobStatus = 'queued' | 'running' | 'paused' | 'done' | 'failed' | 'canceled';

/** Per-job options — mirrors the engine `JobOptions` (camelCase here, snake_case on the wire). */
export interface JobOptions {
  formats: string[];
  dpi?: number;
  pageStart?: number;
  pageEnd?: number;
  pages?: number[];
}

/** Live job progress — mirrors the engine `JobProgress`. */
export interface JobProgress {
  total: number;
  pending: number;
  leased: number;
  done: number;
  failed: number;
  needsReview: number;
  pagesPerMin: number | null;
  etaSeconds: number | null;
}

/** A job row + its live progress — mirrors the engine `JobView`. */
export interface JobView {
  id: string;
  sourceName: string;
  sourcePath: string;
  status: JobStatus;
  totalPages: number;
  priority: number;
  error: string | null;
  createdAt: string;
  updatedAt: string;
  progress: JobProgress;
}

/** Tauri job command names. */
const JOB_CREATE_COMMAND = 'job_create';
const JOB_GET_COMMAND = 'job_get';
const JOB_CANCEL_COMMAND = 'job_cancel';
const JOB_EXPORT_COMMAND = 'job_export';
const SAVE_TEXT_COMMAND = 'save_text';

/** Tauri job event name (the Rust supervisor polls `GET /jobs/{id}` and emits this). */
const JOB_PROGRESS_EVENT = 'engine://job-progress';

interface RawJobProgress {
  total: number;
  pending: number;
  leased: number;
  done: number;
  failed: number;
  needs_review: number;
  pages_per_min: number | null;
  eta_seconds: number | null;
}

interface RawJobView {
  id: string;
  source_name?: string;
  source_path?: string;
  status: JobStatus;
  total_pages?: number;
  priority?: number;
  error?: string | null;
  created_at?: string;
  updated_at?: string;
  progress?: RawJobProgress;
}

function emptyProgress(): JobProgress {
  return {
    total: 0,
    pending: 0,
    leased: 0,
    done: 0,
    failed: 0,
    needsReview: 0,
    pagesPerMin: null,
    etaSeconds: null,
  };
}

function parseJobProgress(raw: RawJobProgress | undefined): JobProgress {
  if (!raw) return emptyProgress();
  return {
    total: raw.total,
    pending: raw.pending,
    leased: raw.leased,
    done: raw.done,
    failed: raw.failed,
    needsReview: raw.needs_review,
    pagesPerMin: raw.pages_per_min,
    etaSeconds: raw.eta_seconds,
  };
}

/**
 * Parse a `JobView` JSON string from Rust into the camelCase TS mirror. Progress-poll error
 * payloads emitted by the Rust bridge are a minimal `{ id, status, error }` object; the
 * optional-field handling below keeps those honest (failed status, zeroed progress).
 */
export function parseJobView(json: string): JobView {
  const raw = JSON.parse(json) as RawJobView;
  return {
    id: raw.id,
    sourceName: raw.source_name ?? '',
    sourcePath: raw.source_path ?? '',
    status: raw.status,
    totalPages: raw.total_pages ?? 0,
    priority: raw.priority ?? 0,
    error: raw.error ?? null,
    createdAt: raw.created_at ?? '',
    updatedAt: raw.updated_at ?? '',
    progress: parseJobProgress(raw.progress),
  };
}

/** Serialize the camelCase `JobOptions` into the engine's snake_case body. */
function toEngineOptions(options: JobOptions): Record<string, unknown> {
  const body: Record<string, unknown> = { formats: options.formats };
  if (options.dpi !== undefined) body.dpi = options.dpi;
  if (options.pageStart !== undefined) body.page_start = options.pageStart;
  if (options.pageEnd !== undefined) body.page_end = options.pageEnd;
  if (options.pages !== undefined) body.pages = options.pages;
  return body;
}

/**
 * Create a PDF→Markdown conversion job for an absolute file path. Rust starts the progress
 * poller; subscribe via `subscribeJobEvents` to drive the UI.
 */
export async function createJob(
  path: string,
  options: JobOptions = { formats: ['md'] },
  priority = 0,
): Promise<JobView> {
  const json = await invoke<string>(JOB_CREATE_COMMAND, {
    path,
    optionsJson: JSON.stringify(toEngineOptions(options)),
    priority,
  });
  return parseJobView(json);
}

/** Fetch a job's current state once. */
export async function getJob(id: string): Promise<JobView> {
  const json = await invoke<string>(JOB_GET_COMMAND, { id });
  return parseJobView(json);
}

/** Request cancellation of an active job; returns the updated view. */
export async function cancelJob(id: string): Promise<JobView> {
  const json = await invoke<string>(JOB_CANCEL_COMMAND, { id });
  return parseJobView(json);
}

/** Fetch the exported Markdown body for a completed job. */
export function getJobMarkdown(id: string): Promise<string> {
  return invoke<string>(JOB_EXPORT_COMMAND, { id, format: 'md' });
}

/**
 * Subscribe to job-progress events. The Rust supervisor polls `GET /jobs/{id}` and emits the
 * raw `JobView` JSON on `engine://job-progress`; parse it into the typed mirror for callers.
 */
export function subscribeJobEvents(callback: (job: JobView) => void): Promise<UnlistenFn> {
  return listen<string>(JOB_PROGRESS_EVENT, (event) => {
    callback(parseJobView(event.payload));
  });
}

// --- native file dialogs (open PDF / save Markdown) -----------------------------------------

/** Open a native file picker for a single PDF; returns the absolute path, or null if canceled. */
export async function pickPdf(): Promise<string | null> {
  const selected = await openDialog({
    multiple: false,
    directory: false,
    filters: [{ name: 'PDF', extensions: ['pdf'] }],
  });
  if (typeof selected === 'string') return selected;
  return null;
}

/**
 * Open a native save dialog for a `.md` file and write `contents` to the chosen path.
 * Returns true if saved, false if the user canceled the dialog.
 */
export async function saveMarkdown(defaultName: string, contents: string): Promise<boolean> {
  const target = await saveDialog({
    defaultPath: defaultName,
    filters: [{ name: 'Markdown', extensions: ['md'] }],
  });
  if (typeof target !== 'string') return false;
  await invoke(SAVE_TEXT_COMMAND, { path: target, contents });
  return true;
}
