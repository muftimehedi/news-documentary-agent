import archiver from 'archiver';
import { Router } from 'express';
import fs from 'node:fs';
import path from 'node:path';
import { requireAuth, type AuthedRequest } from '../middleware/auth.js';
import { getJob } from '../services/jobs.js';
import { buildReview, defaultMeta, jobDir, publishReviewed, retryFailed, saveMeta } from '../services/publishing.js';

const r = Router();
r.use(requireAuth);

function own(job: any, owner: string): boolean { return job && job.owner_id === owner; }

r.get('/:id/meta', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
  res.json(defaultMeta(String(req.params.id)));
});

r.put('/:id/meta', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
  const { title, description } = req.body || {};
  res.json(saveMeta(String(req.params.id), req.ownerId!, String(title || ''), String(description || '')));
});

r.get('/:id/review', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
  const p = path.join(jobDir(String(req.params.id)), 'publish_review.json');
  if (!fs.existsSync(p)) { res.status(404).json({ error: 'No review yet' }); return; }
  res.json(JSON.parse(fs.readFileSync(p, 'utf8')));
});

// Explicit authorization step 1: Review & authorize (binds video hash + metadata + destinations).
r.post('/:id/review', async (req: AuthedRequest, res) => {
  try {
    const j = await getJob(String(req.params.id));
    if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
    const { title, description, selections } = req.body || {};
    if (title !== undefined || description !== undefined) saveMeta(String(req.params.id), req.ownerId!, String(title || ''), String(description || ''));
    const review = await buildReview(req.ownerId!, String(req.params.id), selections || []);
    res.json(review);
  } catch (e: any) { res.status(e.permanent ? 422 : 500).json({ error: String(e.message).slice(0, 500) }); }
});

// Explicit authorization step 2: Publish the reviewed version (agent can never do this).
r.post('/:id/publish', async (req: AuthedRequest, res) => {
  try {
    const j = await getJob(String(req.params.id));
    if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
    res.json(await publishReviewed(req.ownerId!, String(req.params.id)));
  } catch (e: any) { res.status(e.permanent ? 422 : 500).json({ error: String(e.message).slice(0, 500) }); }
});

r.post('/:id/retry', async (req: AuthedRequest, res) => {
  try {
    const j = await getJob(String(req.params.id));
    if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
    res.json(await retryFailed(req.ownerId!, String(req.params.id)));
  } catch (e: any) { res.status(e.permanent ? 422 : 500).json({ error: String(e.message).slice(0, 500) }); }
});

r.get('/:id/publications', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!own(j, req.ownerId!)) { res.status(404).json({ error: 'Not found' }); return; }
  const { getDb } = await import('../db.js');
  const db = await getDb();
  const { rows } = await db.query('SELECT logical_key, destination, account_id, remote_id, url, visibility, status, created_at FROM publications WHERE job_id = ? ORDER BY created_at DESC', [String(req.params.id)]);
  res.json(rows);
});

export default r;
