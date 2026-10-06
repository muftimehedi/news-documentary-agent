// Typed contracts v1 — mirrors packages/contracts/v1.json.
// Queue payloads carry job IDs + artifact references, never large media.

export type JobStatus =
  | 'queued' | 'leased' | 'running' | 'awaiting-approval' | 'approved'
  | 'publishing' | 'published' | 'failed' | 'cancelled'
  | 'blocked-no-evidence' | 'reviewed-failed' | 'done';

export type JobStage =
  | 'discover' | 'choose_topic' | 'research' | 'fact_check' | 'script'
  | 'prepare_media' | 'render' | 'review' | 'approval' | 'publish'
  | 'record_result' | 'done';

export interface ProductionSettings {
  topic: string;
  language?: string; // default 'en', 'bn' supported
  duration_seconds?: number;
  aspect_ratio?: 'vertical' | 'horizontal';
  narration_style?: string;
  tts_provider?: 'fixture' | 'gtts';
  video_provider?: 'stills' | 'veo';
  veo_model?: string;
}

export interface JobRecord {
  job_id: string;
  owner_id: string;
  thread_id: string;
  topic: string;
  status: JobStatus;
  stage: JobStage;
  settings: ProductionSettings;
  worker_id?: string | null;
  lease_expires_at?: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
}

export interface ProgressEvent {
  id?: number;
  job_id: string;
  kind: string; // readable: research-started, fact-check-completed, ...
  message: string;
  stage?: JobStage;
  status?: string;
  data?: Record<string, unknown>;
  created_at?: string;
}

export interface ArtifactRef {
  name: string;
  path: string;
  content_type?: string;
  size_bytes?: number;
  sha256?: string;
}

export interface ChatMessage {
  id?: number;
  thread_id: string;
  owner_id?: string;
  role: 'user' | 'agent';
  content: string;
  job_id?: string | null;
  created_at?: string;
}

export interface AccountRef {
  account_id: string;
  platform: 'youtube' | 'facebook' | 'x' | 'hikmah' | 'fixture';
  label?: string;
  visibility?: 'public' | 'unlisted' | 'private';
}

export interface PublishReview {
  job_id: string;
  video_sha256: string;
  script_version: number;
  title: string;
  description: string;
  selections: AccountRef[];
  metadata_hash: string;
}

export interface PublishResult {
  platform: string;
  account_id?: string;
  status: 'succeeded' | 'succeeded-fixture' | 'failed-permanent' | 'failed-retryable' | 'unknown-timeout' | 'skipped';
  remote_id?: string;
  url?: string;
  note?: string;
  fixture?: boolean;
}

export const CONTRACT_VERSION = '1';

// Readable progress kinds shown in UI (never raw ToolCallRequest objects)
export const READABLE_EVENTS = [
  'research-started',
  'fact-check-completed',
  'script-ready',
  'generating-narration',
  'rendering-video',
  'video-ready',
  'upload-completed',
] as const;
