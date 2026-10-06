// Typed contracts v2 — doc scope (PDF reports + social posts).
// v1 (video) remains valid for preserved history only.

export type JobType = 'report' | 'social';

export type DocStage =
  | 'discover' | 'choose_topic' | 'research' | 'fact_check' | 'write'
  | 'review' | 'approval' | 'publish' | 'record_result' | 'done';

export type DocStatus =
  | 'queued' | 'leased' | 'running' | 'awaiting-approval' | 'approved'
  | 'ready_for_user' | 'publishing' | 'published' | 'failed' | 'cancelled'
  | 'blocked-no-evidence' | 'reviewed-failed' | 'done';

export interface DocProductionSettings {
  topic: string;
  job_type?: JobType;
  platforms?: string[];
  language?: string; // default 'en', 'bn' supported (PDF needs DOC_FONT_TTF)
  revision_note?: string;
}

export interface SocialPost {
  text: string;
  title?: string;
  description?: string;
  claim_ids: string[];
  chars: number;
  /** False = disabled for connected posting (e.g. YouTube text). */
  connect_post: boolean;
  note?: string;
}

export const CONTRACT_VERSION = '2';

// Hard per-platform character limits enforced by the writer.
export const PLATFORM_LIMITS: Record<string, number> = {
  x: 280,
  facebook: 2000,
  hikmah: 20000,
  youtube: 5000,
};

// Platforms disabled for connected text posting, with the reason shown in UI.
export const TEXT_POST_DISABLED: Record<string, string> = {
  youtube: 'YouTube Data API v3 has no text/community-post endpoint (video upload and comments only). Use the generated title/description manually.',
};

export const READABLE_DOC_EVENTS = [
  'research-started',
  'fact-check-completed',
  'write-ready',
  'review-ready',
  'upload-completed',
] as const;
