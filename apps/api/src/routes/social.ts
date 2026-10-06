import { Router } from 'express';
import fs from 'node:fs';
import { requireAuth, type AuthedRequest } from '../middleware/auth.js';
import { getJob } from '../services/jobs.js';
import { buildTextReview, defaultTexts, publishTextReviewed, retryTextFailed, saveTexts, socialPaths } from '../services/social.js';

const r = Router();
r.use(requireAuth);

function own(job: any, owner: string): boolean { return job && job.owner_id === owner; }

// Generated posts (worker output, before/after user edits).
r.get('/:id/texts', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
  const jp = socialPaths(String(req.params.id));
  const generated = (() => { try { return JSON.parse(fs.readFileSync(jp.posts, 'utf8')); } catch { return {}; } })();
  res.json({ texts: defaultTexts(String(req.params.id)), generated });
});

// User edits (draft — not yet authorized).
r.put('/:id/texts', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
  const { texts } = req.body || {};
  if (!texts || typeof texts !== 'object') { res.status(400).json({ error: 'texts object required' }); return; }
  res.json({ texts: saveTexts(String(req.params.id), req.ownerId!, texts) });
});

r.get('/:id/review', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
  const p = socialPaths(String(req.params.id)).review;
  if (!fs.existsSync(p)) { res.status(404).json({ error: 'No review yet' }); return; }
  res.json(JSON.parse(fs.readFileSync(p, 'utf8')));
});

// Step 1: Review & authorize exact texts + destinations.
r.post('/:id/review', async (req: AuthedRequest, res) => {
  try {
    const j = await getJob(String(req.params.id));
    if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
    const { texts, selections } = req.body || {};
    if (texts) saveTexts(String(req.params.id), req.ownerId!, texts);
    res.json(await buildTextReview(req.ownerId!, String(req.params.id), selections || []));
  } catch (e: any) { res.status(e.permanent ? 422 : 500).json({ error: String(e.message).slice(0, 500) }); }
});

// Step 2: Publish the reviewed texts (agent can never do this).
r.post('/:id/publish', async (req: AuthedRequest, res) => {
  try {
    const j = await getJob(String(req.params.id));
    if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
    res.json(await publishTextReviewed(req.ownerId!, String(req.params.id)));
  } catch (e: any) { res.status(e.permanent ? 422 : 500).json({ error: String(e.message).slice(0, 500) }); }
});

r.post('/:id/retry', async (req: AuthedRequest, res) => {
  try {
    const j = await getJob(String(req.params.id));
    if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
    res.json(await retryTextFailed(req.ownerId!, String(req.params.id)));
  } catch (e: any) { res.status(e.permanent ? 422 : 500).json({ error: String(e.message).slice(0, 500) }); }
});

r.get('/:id/publications', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
  const { getDb } = await import('../db.js');
  const db = await getDb();
  const { rows } = await db.query(
    `SELECT logical_key, destination, account_id, remote_id, url, visibility, status, created_at FROM publications
     WHERE job_id = ? AND logical_key LIKE 'text:%' ORDER BY created_at DESC`, [String(req.params.id)]);
  res.json(rows);
});

export default r;
