// Connected publishing: review binding + per-destination results.
// Connecting never publishes. Publish requires explicit review (video hash +
// metadata + destinations). Changes invalidate the review.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { getDb, nowIso } from '../db.js';
import { AdapterError, getAdapter } from './adapters.js';
import { getAccount, loadSecret } from './vault.js';

export function jobDir(jobId: string): string {
  const root = process.env.JOB_ROOT || 'data/jobs';
  return path.join(root, jobId);
}

export function sha256File(p: string): string {
  const h = crypto.createHash('sha256');
  const fd = fs.openSync(p, 'r');
  const buf = Buffer.alloc(65536);
  let n: number;
  do { n = fs.readSync(fd, buf, 0, buf.length, null); if (n) h.update(buf.subarray(0, n)); } while (n > 0);
  fs.closeSync(fd);
  return h.digest('hex');
}

export function metadataHash(title: string, description: string, selections: any[]): string {
  const norm = JSON.stringify({
    title, description,
    destinations: [...selections].map((s: any) => [s.account_id, s.platform, s.visibility]).sort(),
  });
  return crypto.createHash('sha256').update(norm, 'utf8').digest('hex');
}

function readJson(p: string, fallback: any = null): any {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return fallback; }
}

export function defaultMeta(jobId: string): { title: string; description: string; source_links: string[] } {
  const dir = jobDir(jobId);
  const saved = readJson(path.join(dir, 'publish_meta.json'), null);
  if (saved?.title) return { title: saved.title, description: saved.description || '', source_links: saved.source_links || [] };
  const script = readJson(path.join(dir, 'script.json'), {});
  // Doc scope: report summary doubles as the description when no video script exists.
  const report = readJson(path.join(dir, 'posts.json'), null);
  const links: string[] = [];
  try {
    const sources = readJson(path.join(dir, 'sources.json'), []);
    for (const s of (Array.isArray(sources) ? sources : []).slice(0, 8)) if (s?.url) links.push(s.url);
  } catch { /* ignore */ }
  if (!script?.title && report) {
    const first = Object.values(report as Record<string, any>)[0] as any;
    return { title: (first?.title || jobId).slice(0, 100), description: (first?.text || '').slice(0, 1500), source_links: links };
  }
  const sources = readJson(path.join(dir, 'sources.json'), []);
  return {
    title: (script?.title || jobId).slice(0, 100),
    description: (script?.narration_full || '').slice(0, 1500),
    source_links: [...links, ...((Array.isArray(sources) ? sources : []).map((s: any) => s?.url).filter(Boolean).slice(0, 8))].slice(0, 8),
  };
}

export function saveMeta(jobId: string, owner: string, title: string, description: string) {
  const dir = jobDir(jobId);
  fs.mkdirSync(dir, { recursive: true });
  const meta = { ...defaultMeta(jobId), title: title.slice(0, 200), description: description.slice(0, 5000), edited_by: owner, edited_at: nowIso() };
  fs.writeFileSync(path.join(dir, 'publish_meta.json'), JSON.stringify(meta, null, 2));
  return meta;
}

export async function buildReview(owner: string, jobId: string, selections: { account_id: string; visibility: string }[]) {
  const dir = jobDir(jobId);
  const video = path.join(dir, 'documentary.mp4');
  if (!fs.existsSync(video)) throw new AdapterError('No rendered video for this job yet.', true);
  const meta = defaultMeta(jobId);
  const sels: any[] = [];
  for (const s of selections) {
    const acc = await getAccount(owner, s.account_id);
    if (!acc || acc.status !== 'connected') throw new AdapterError(`Account ${s.account_id} is not connected (owner-scoped).`, true);
    const vis = (s as any).visibility || 'public';
    const adapter = getAdapter(acc.platform);
    const errs = await adapter.validate(video, meta.title, meta.description, vis);
    if (errs.length) throw new AdapterError(`${acc.platform} validation: ${errs.join('; ')}`, true);
    sels.push({ account_id: acc.id, platform: acc.platform, label: acc.label, visibility: vis });
  }
  if (!sels.length) throw new AdapterError('Select at least one connected account.', true);
  const script = readJson(path.join(dir, 'script.json'), {});
  const review = {
    job_id: jobId, owner, video_hash: sha256File(video),
    script_version: script?.version || 1, title: meta.title,
    description: meta.description, source_links: meta.source_links, selections: sels,
    metadata_hash: metadataHash(meta.title, meta.description, sels),
    reviewed_by: owner, reviewed_at: nowIso(),
  };
  fs.writeFileSync(path.join(dir, 'publish_review.json'), JSON.stringify(review, null, 2));
  fs.writeFileSync(path.join(dir, 'approval.json'), JSON.stringify({
    approved: true, video_hash: review.video_hash, script_version: review.script_version,
    metadata_hash: review.metadata_hash,
    destinations: sels.map((s) => `${s.platform}:${s.account_id}`), by: owner, at: review.reviewed_at,
  }, null, 2));
  return review;
}

function logicalKey(jobId: string, accountId: string, videoHash: string): string {
  return `${jobId}:${accountId}:${videoHash.slice(0, 16)}`;
}

async function claimSlot(key: string, jobId: string, dest: string, hash: string, accountId: string, owner: string): Promise<boolean> {
  const db = await getDb();
  try {
    await db.query(
      `INSERT INTO publications(logical_key, job_id, destination, account_id, owner, artifact_hash, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'intent', ?)`,
      [key, jobId, dest, accountId, owner, hash, nowIso()],
    );
    return true;
  } catch { return false; }
}

async function getPub(key: string): Promise<any | null> {
  const db = await getDb();
  const { rows } = await db.query('SELECT * FROM publications WHERE logical_key = ?', [key]);
  return rows[0] || null;
}

async function recordReceipt(key: string, receipt: any) {
  const db = await getDb();
  await db.query(
    `UPDATE publications SET remote_id=?, url=?, visibility=?, status=?, response=? WHERE logical_key=?`,
    [receipt.remote_id || '', receipt.url || '', receipt.visibility || '', receipt.status || '', JSON.stringify(receipt), key],
  );
}

async function uploadOne(owner: string, review: any, sel: any, video: string): Promise<any> {
  const key = logicalKey(review.job_id, sel.account_id, review.video_hash);
  const existing = await getPub(key);
  if (existing && String(existing.status || '').startsWith('succeeded')) {
    return { account_id: sel.account_id, platform: sel.platform, skipped: true, reason: 'already-succeeded', ...existing };
  }
  if (existing && existing.status === 'unknown-timeout') {
    return { account_id: sel.account_id, platform: sel.platform, skipped: true, reason: 'needs-operator-resolution', ...existing };
  }
  if (!existing) await claimSlot(key, review.job_id, sel.platform, review.video_hash, sel.account_id, owner);
  const acc = await getAccount(owner, sel.account_id);
  if (!acc || acc.status !== 'connected') {
    const res = { destination: sel.platform, status: 'failed-permanent', note: 'account disconnected before upload', fixture: false };
    await recordReceipt(key, res);
    return { account_id: sel.account_id, platform: sel.platform, ...res };
  }
  let secret: any;
  try { secret = await loadSecret(owner, sel.account_id); } catch (e: any) {
    const res = { destination: sel.platform, status: 'failed-permanent', note: `credential unavailable: ${e.message}`, fixture: false };
    await recordReceipt(key, res);
    return { account_id: sel.account_id, platform: sel.platform, ...res };
  }
  try {
    const receipt = await getAdapter(sel.platform).upload(video, review.title, review.description, sel.visibility, secret);
    await recordReceipt(key, receipt);
    return { account_id: sel.account_id, platform: sel.platform, skipped: false, ...receipt };
  } catch (e: any) {
    if (e instanceof AdapterError) {
      const res = { destination: sel.platform, status: e.permanent ? 'failed-permanent' : 'failed-retryable', note: String(e.message).slice(0, 400), fixture: false };
      await recordReceipt(key, res);
      return { account_id: sel.account_id, platform: sel.platform, ...res };
    }
    const res = { destination: sel.platform, status: 'unknown-timeout', note: `ambiguous failure, needs operator resolution: ${String(e?.message || e).slice(0, 300)}`, fixture: false };
    await recordReceipt(key, res);
    return { account_id: sel.account_id, platform: sel.platform, ...res };
  }
}

export async function publishReviewed(owner: string, jobId: string) {
  const dir = jobDir(jobId);
  const reviewPath = path.join(dir, 'publish_review.json');
  if (!fs.existsSync(reviewPath)) throw new AdapterError('No review found. Review & authorize before publishing.', true);
  const review = JSON.parse(fs.readFileSync(reviewPath, 'utf8'));
  if (review.owner !== owner) throw new AdapterError('Review belongs to another owner.', true);
  const video = path.join(dir, 'documentary.mp4');
  if (!fs.existsSync(video)) throw new AdapterError('Reviewed video file is missing.', true);
  if (sha256File(video) !== review.video_hash) throw new AdapterError('Video changed after review — authorize a new review first.', true);
  const meta = defaultMeta(jobId);
  if (metadataHash(meta.title, meta.description, review.selections) !== review.metadata_hash) {
    throw new AdapterError('Title/description/destinations changed after review — authorize again.', true);
  }
  const results: any[] = [];
  for (const sel of review.selections) {
    let attempt = 0, res: any = null;
    while (true) {
      res = await uploadOne(owner, review, sel, video);
      if (res?.status === 'failed-retryable' && !res?.skipped && attempt < 2) { attempt++; await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt)); continue; }
      break;
    }
    results.push(res);
  }
  const db = await getDb();
  const ok = results.some((r) => String(r?.status || '').startsWith('succeeded'));
  await db.query(`UPDATE jobs SET status=?, updated_at=? WHERE job_id=?`, [ok ? 'published' : 'publish-partial-or-failed', nowIso(), jobId]);
  return results;
}

export async function retryFailed(owner: string, jobId: string) {
  return publishReviewed(owner, jobId); // succeeded destinations skip via logical keys
}
