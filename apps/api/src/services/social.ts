// Connected text publishing (doc scope): review binding + per-destination posts.
// Same rules as video publishing: connecting never publishes; explicit
// Review & authorize (content hash + destinations) then Publish; changes need
// a new review; failures never erase successes; duplicates skipped by logical
// keys; ambiguous failures need operator resolution, never blind retry.
// Platforms WITHOUT a text adapter (YouTube) are refused with an explanation
// instead of reusing video-upload adapters.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { getDb, nowIso } from '../db.js';
import { AdapterError, getAdapter } from './adapters.js';
import { jobDir } from './publishing.js';
import { getAccount, loadSecret } from './vault.js';

export function socialPaths(jobId: string) {
  const dir = jobDir(jobId);
  return { dir, posts: path.join(dir, 'posts.json'), meta: path.join(dir, 'social_meta.json'), review: path.join(dir, 'social_review.json') };
}

function readJson(p: string, fallback: any = null): any {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return fallback; }
}

export function defaultTexts(jobId: string): Record<string, string> {
  const jp = socialPaths(jobId);
  const saved = readJson(jp.meta, null);
  if (saved?.texts) return saved.texts;
  const posts = readJson(jp.posts, {});
  const out: Record<string, string> = {};
  for (const [plat, p] of Object.entries(posts as Record<string, any>)) out[plat] = p?.text || '';
  return out;
}

export function saveTexts(jobId: string, owner: string, texts: Record<string, string>) {
  const jp = socialPaths(jobId);
  fs.mkdirSync(jp.dir, { recursive: true });
  const clean: Record<string, string> = {};
  for (const [k, v] of Object.entries(texts || {}).slice(0, 10)) clean[String(k).slice(0, 32)] = String(v || '').slice(0, 20000);
  const meta = { texts: { ...defaultTexts(jobId), ...clean }, edited_by: owner, edited_at: nowIso() };
  fs.writeFileSync(jp.meta, JSON.stringify(meta, null, 2));
  return meta.texts;
}

export function contentHash(texts: Record<string, string>, selections: any[]): string {
  const norm = JSON.stringify({
    texts: Object.fromEntries(Object.entries(texts).sort()),
    destinations: [...selections].map((s: any) => [s.account_id, s.platform]).sort(),
  });
  return crypto.createHash('sha256').update(norm, 'utf8').digest('hex');
}

export async function buildTextReview(owner: string, jobId: string, selections: { account_id: string }[]) {
  const jp = socialPaths(jobId);
  if (!Object.keys(defaultTexts(jobId)).length) throw new AdapterError('No generated posts for this job yet.', true);
  const texts = defaultTexts(jobId);
  const sels: any[] = [];
  for (const s of selections) {
    const acc = await getAccount(owner, s.account_id);
    if (!acc || acc.status !== 'connected') throw new AdapterError(`Account ${s.account_id} is not connected (owner-scoped).`, true);
    const adapter = getAdapter(acc.platform);
    if (!adapter.postText || !adapter.validateText) {
      throw new AdapterError(
        `${adapter.display}: connected text posting is not supported — ${platformTextBlockReason(acc.platform)}. The generated text remains available for manual copy/download.`,
        true);
    }
    const text = texts[acc.platform] ?? '';
    const errs = await adapter.validateText!(text);
    if (errs.length) throw new AdapterError(`${acc.platform} validation: ${errs.join('; ')}`, true);
    sels.push({ account_id: acc.id, platform: acc.platform, label: acc.label });
  }
  if (!sels.length) throw new AdapterError('Select at least one connected account.', true);
  const review = {
    job_id: jobId, owner, texts,
    selections: sels, content_hash: contentHash(texts, sels),
    reviewed_by: owner, reviewed_at: nowIso(),
  };
  fs.writeFileSync(jp.review, JSON.stringify(review, null, 2));
  return review;
}

export function platformTextBlockReason(platform: string): string {
  if (platform === 'youtube') {
    return 'YouTube Data API v3 exposes video upload, comments and captions only — there is no text/community-post endpoint, so a video-upload adapter must never be reused for text.';
  }
  return `no verified text-post API for ${platform}`;
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

async function uploadTextOne(owner: string, review: any, sel: any): Promise<any> {
  const key = `text:${review.job_id}:${sel.account_id}:${review.content_hash.slice(0, 16)}`;
  const existing = await getPub(key);
  if (existing && String(existing.status || '').startsWith('succeeded')) {
    return { account_id: sel.account_id, platform: sel.platform, skipped: true, reason: 'already-succeeded', ...existing };
  }
  if (existing && existing.status === 'unknown-timeout') {
    return { account_id: sel.account_id, platform: sel.platform, skipped: true, reason: 'needs-operator-resolution', ...existing };
  }
  if (!existing) {
    const db = await getDb();
    try {
      await db.query(
        `INSERT INTO publications(logical_key, job_id, destination, account_id, owner, artifact_hash, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'intent', ?)`,
        [key, review.job_id, sel.platform, sel.account_id, owner, review.content_hash, nowIso()],
      );
    } catch { /* raced claim: fall through to re-read */ }
  }
  const acc = await getAccount(owner, sel.account_id);
  if (!acc || acc.status !== 'connected') {
    const res = { destination: sel.platform, status: 'failed-permanent', note: 'account disconnected before posting', fixture: false };
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
    const receipt = await getAdapter(sel.platform).postText!(review.texts[sel.platform] || '', secret);
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

export async function publishTextReviewed(owner: string, jobId: string) {
  const jp = socialPaths(jobId);
  if (!fs.existsSync(jp.review)) throw new AdapterError('No text review found. Review & authorize before publishing.', true);
  const review = JSON.parse(fs.readFileSync(jp.review, 'utf8'));
  if (review.owner !== owner) throw new AdapterError('Review belongs to another owner.', true);
  const current = defaultTexts(jobId);
  if (contentHash(current, review.selections) !== review.content_hash) {
    throw new AdapterError('Post text or destinations changed after review — authorize again.', true);
  }
  const results: any[] = [];
  for (const sel of review.selections) {
    let attempt = 0, res: any = null;
    while (true) {
      res = await uploadTextOne(owner, review, sel);
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

export async function retryTextFailed(owner: string, jobId: string) {
  return publishTextReviewed(owner, jobId);
}
