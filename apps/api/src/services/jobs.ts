// Durable background job queue compatible with Node.js and Python.
// Mechanism: shared SQL jobs table + worker leases. No Node-specific queue
// library (BullMQ etc.) so Python can participate via the HTTP API.
// Closing browser/terminal never cancels: rows persist; leases expire;
// crash recovery re-queues expired leases; duplicate execution prevented
// by atomic lease claim (UPDATE ... WHERE status='queued' OR lease expired).
import { getDb, newId, nowIso } from '../db.js';

export interface JobSettings {
  topic: string;
  job_type?: 'report' | 'social';
  platforms?: string[];
  language?: string;
  revision_note?: string;
  // Legacy video scope (preserved for history; rejected for new jobs).
  duration_seconds?: number;
  aspect_ratio?: 'vertical' | 'horizontal';
  narration_style?: string;
  tts_provider?: 'fixture' | 'gtts';
  video_provider?: 'stills' | 'veo';
  veo_model?: string;
}

export const ACTIVE_JOB_TYPES = ['report', 'social'] as const;

const LEASE_SECONDS = Number(process.env.WORKER_LEASE_SECONDS || 300);

export async function createJob(owner: string, topic: string, settings: JobSettings, threadId?: string) {
  const db = await getDb();
  const job_type = (settings.job_type || 'report').toLowerCase();
  if (!(ACTIVE_JOB_TYPES as readonly string[]).includes(job_type)) {
    throw Object.assign(
      new Error(`Unsupported job_type=${JSON.stringify((settings as any).job_type)}. Active scope: report | social. Video generation is disabled (legacy code preserved).`),
      { status: 400 });
  }
  const job_id = newId('job');
  const thread_id = threadId || `thread-${job_id}`;
  const full: JobSettings = {
    topic, job_type: job_type as 'report' | 'social',
    platforms: settings.platforms || ['x', 'facebook', 'hikmah'],
    language: settings.language || 'en',
    revision_note: settings.revision_note || '',
  };
  const now = nowIso();
  // job_type column exists after migration 002; older DBs without it fall back
  // to the settings snapshot (rowToJob reads both).
  try {
    await db.query(
      `INSERT INTO jobs(job_id, owner, thread_id, topic, status, stage, settings, job_type, attempts, created_at, updated_at)
       VALUES (?, ?, ?, ?, 'queued', 'discover', ?, ?, 0, ?, ?)`,
      [job_id, owner, thread_id, topic, JSON.stringify(full), job_type, now, now],
    );
  } catch {
    await db.query(
      `INSERT INTO jobs(job_id, owner, thread_id, topic, status, stage, settings, attempts, created_at, updated_at)
       VALUES (?, ?, ?, ?, 'queued', 'discover', ?, 0, ?, ?)`,
      [job_id, owner, thread_id, topic, JSON.stringify(full), now, now],
    );
  }
  await addEvent(job_id, 'job-queued', `Queued ${job_type}: ${topic}`.slice(0, 300), 'discover', 'queued', { job_type });
  return getJob(job_id);
}

export async function getJob(job_id: string) {
  const db = await getDb();
  const { rows } = await db.query('SELECT * FROM jobs WHERE job_id = ?', [job_id]);
  if (!rows.length) return null;
  return rowToJob(rows[0]);
}

export async function listJobs(owner: string, limit = 50) {
  const db = await getDb();
  const { rows } = await db.query('SELECT * FROM jobs WHERE owner = ? ORDER BY created_at DESC LIMIT ?', [owner, limit]);
  return rows.map(rowToJob);
}

function rowToJob(r: any) {
  const settings = safeJson(r.settings);
  return {
    job_id: r.job_id, owner_id: r.owner, thread_id: r.thread_id, topic: r.topic,
    status: r.status, stage: r.stage, settings,
    job_type: r.job_type || settings.job_type || 'report',
    worker_id: r.worker_id || null, lease_expires_at: r.lease_expires_at || null,
    attempts: r.attempts || 0, created_at: r.created_at, updated_at: r.updated_at,
  };
}

// Explicit user revision: store the note, invalidate prior approval, requeue.
// Only the write/review stages rerun (research + fact-check artifacts reused).
export async function reviseJob(job_id: string, owner: string, note: string) {
  const db = await getDb();
  const j = await getJob(job_id);
  if (!j || (j as any).owner_id !== owner) throw Object.assign(new Error('Not found'), { status: 404 });
  const settings = { ...(j as any).settings, revision_note: String(note || '').slice(0, 1000) };
  await db.query(`UPDATE jobs SET settings=?, status='queued', stage='write', lease_expires_at=NULL, worker_id=NULL, updated_at=? WHERE job_id=?`,
    [JSON.stringify(settings), nowIso(), job_id]);
  await addEvent(job_id, 'job-revised', `Revision requested: ${String(note || '').slice(0, 200)}`, 'write', 'queued', {});
  // Stale approval must never authorize the rewritten output.
  try {
    const { jobDir } = await import('./publishing.js');
    const fs = await import('node:fs');
    const path = await import('node:path');
    for (const f of ['approval.json', 'publish_review.json', 'social_review.json']) {
      const p = path.join(jobDir(job_id), f);
      if (fs.existsSync(p)) fs.unlinkSync(p);
    }
  } catch { /* best effort */ }
  return getJob(job_id);
}

function safeJson(s: string) { try { return JSON.parse(s || '{}'); } catch { return {}; } }

export async function addEvent(job_id: string, kind: string, message: string, stage = '', status = '', data: any = {}) {
  const db = await getDb();
  await db.query(
    `INSERT INTO job_events(job_id, kind, message, stage, status, data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [job_id, kind, message, stage, status, JSON.stringify(data || {}), nowIso()],
  );
}

export async function getEvents(job_id: string, afterId = 0, limit = 200) {
  const db = await getDb();
  const { rows } = await db.query(
    'SELECT * FROM job_events WHERE job_id = ? AND id > ? ORDER BY id ASC LIMIT ?', [job_id, afterId, limit]);
  return rows.map((r: any) => ({
    id: r.id, job_id: r.job_id, kind: r.kind, message: r.message,
    stage: r.stage, status: r.status, data: safeJson(r.data), created_at: r.created_at,
  }));
}

export async function updateJobProgress(job_id: string, patch: { status?: string; stage?: string; error?: string; cost_usd?: number; model_calls?: number }) {
  const db = await getDb();
  const sets: string[] = ['updated_at = ?'];
  const vals: any[] = [nowIso()];
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) continue;
    sets.push(`${k} = ?`); vals.push(v);
  }
  vals.push(job_id);
  await db.query(`UPDATE jobs SET ${sets.join(', ')} WHERE job_id = ?`, vals);
}

// Atomic lease claim: only one worker wins. Prevents duplicate execution.
export async function claimNextJob(workerId: string) {
  const db = await getDb();
  const now = nowIso();
  const { rows } = await db.query(
    `SELECT * FROM jobs WHERE status = 'queued' OR (status IN ('leased','running') AND lease_expires_at IS NOT NULL AND lease_expires_at < ?)
     ORDER BY created_at ASC LIMIT 5`, [now]);
  for (const r of rows) {
    const leaseExp = new Date(Date.now() + LEASE_SECONDS * 1000).toISOString();
    const res = await db.query(
      `UPDATE jobs SET status='leased', worker_id=?, lease_expires_at=?, attempts=attempts+1, updated_at=?
       WHERE job_id=? AND (status='queued' OR (lease_expires_at IS NOT NULL AND lease_expires_at < ?))`,
      [workerId, leaseExp, now, r.job_id, now],
    );
    void res;
    const check = await getJob(r.job_id);
    if (check && check.worker_id === workerId && check.status === 'leased') {
      // Re-read to confirm we won (sqlite has no RETURNING count guarantee here).
      await addEvent(r.job_id, 'job-leased', `Leased by ${workerId}`, check.stage, 'leased', { workerId });
      return check;
    }
  }
  return null;
}

export async function heartbeat(job_id: string, workerId: string, patch: { status?: string; stage?: string } = {}) {
  const leaseExp = new Date(Date.now() + LEASE_SECONDS * 1000).toISOString();
  const db = await getDb();
  const { rows } = await db.query('SELECT worker_id FROM jobs WHERE job_id = ?', [job_id]);
  if (!rows.length) throw Object.assign(new Error('Job not found'), { status: 404 });
  if (rows[0].worker_id && rows[0].worker_id !== workerId) {
    throw Object.assign(new Error('Lease held by another worker'), { status: 409 });
  }
  const sets = ['worker_id = ?', 'lease_expires_at = ?', 'updated_at = ?'];
  const vals: any[] = [workerId, leaseExp, nowIso()];
  if (patch.status) { sets.push('status = ?'); vals.push(patch.status); }
  if (patch.stage) { sets.push('stage = ?'); vals.push(patch.stage); }
  vals.push(job_id);
  await db.query(`UPDATE jobs SET ${sets.join(', ')} WHERE job_id = ?`, vals);
}

export async function cancelJob(job_id: string, owner: string) {
  const db = await getDb();
  const { rows } = await db.query('SELECT owner FROM jobs WHERE job_id = ?', [job_id]);
  if (!rows.length) throw Object.assign(new Error('Job not found'), { status: 404 });
  if (rows[0].owner !== owner) throw Object.assign(new Error('Forbidden'), { status: 403 });
  await db.query(`UPDATE jobs SET status='cancelled', updated_at=? WHERE job_id=?`, [nowIso(), job_id]);
  await addEvent(job_id, 'job-cancelled', 'Cancelled by user request', '', 'cancelled', {});
}

export async function saveArtifact(job_id: string, name: string, relPath: string, contentType = '', sizeBytes = 0, sha256 = '') {
  const db = await getDb();
  if (db.dialect === 'pg') {
    await db.query(
      `INSERT INTO artifacts(job_id, name, path, content_type, size_bytes, sha256, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (job_id, name) DO UPDATE SET path=EXCLUDED.path, content_type=EXCLUDED.content_type, size_bytes=EXCLUDED.size_bytes, sha256=EXCLUDED.sha256`,
      [job_id, name, relPath, contentType, sizeBytes, sha256, nowIso()],
    );
  } else {
    await db.query(
      `INSERT INTO artifacts(job_id, name, path, content_type, size_bytes, sha256, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(job_id, name) DO UPDATE SET path=excluded.path, content_type=excluded.content_type, size_bytes=excluded.size_bytes, sha256=excluded.sha256`,
      [job_id, name, relPath, contentType, sizeBytes, sha256, nowIso()],
    );
  }
}

export async function listArtifacts(job_id: string) {
  const db = await getDb();
  const { rows } = await db.query('SELECT * FROM artifacts WHERE job_id = ?', [job_id]);
  return rows;
}
