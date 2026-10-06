import { Router } from 'express';
import { requireAuth, type AuthedRequest } from '../middleware/auth.js';
import { verifyToken } from '../services/auth.js';
import { addEvent, cancelJob, createJob, getEvents, getJob, heartbeat, claimNextJob, listJobs, saveArtifact, updateJobProgress, listArtifacts } from '../services/jobs.js';
import { requireService } from '../middleware/auth.js';
import { getDb } from '../db.js';

const r = Router();
r.use('/internal', requireService);

r.post('/', requireAuth, async (req: AuthedRequest, res) => {
  try {
    const { topic, settings, thread_id } = req.body || {};
    if (!topic || typeof topic !== 'string') { res.status(400).json({ error: 'topic required' }); return; }
    const job = await createJob(req.ownerId!, topic, { ...(settings || {}), topic }, thread_id);
    res.status(201).json(job);
  } catch (e: any) { res.status(e.status || 500).json({ error: e.message }); }
});

r.get('/', requireAuth, async (req: AuthedRequest, res) => {
  res.json(await listJobs(req.ownerId!));
});

r.get('/:id', requireAuth, async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!j || (j as any).owner_id !== req.ownerId) { res.status(404).json({ error: 'Not found' }); return; }
  res.json(j);
});

r.post('/:id/cancel', requireAuth, async (req: AuthedRequest, res) => {
  try { await cancelJob(String(req.params.id), req.ownerId!); res.json({ ok: true }); }
  catch (e: any) { res.status(e.status || 500).json({ error: e.message }); }
});

r.post('/:id/resume', requireAuth, async (req: AuthedRequest, res) => {
  try {
    const j = await getJob(String(req.params.id));
    if (!j || (j as any).owner_id !== req.ownerId) { res.status(404).json({ error: 'Not found' }); return; }
    const db = await getDb();
    const { nowIso } = await import('../db.js');
    await db.query(`UPDATE jobs SET status='queued', lease_expires_at=NULL, worker_id=NULL, updated_at=? WHERE job_id=?`, [nowIso(), String(req.params.id)]);
    await addEvent(String(req.params.id), 'job-resumed', 'Resume requested by user', '', 'queued', {});
    res.json(await getJob(String(req.params.id)));
  } catch (e: any) { res.status(e.status || 500).json({ error: e.message }); }
});

// Explicit revision: stores the note, invalidates stale approval, requeues.
// The worker reuses research + fact-check and reruns write → review.
r.post('/:id/revise', requireAuth, async (req: AuthedRequest, res) => {
  try {
    const { reviseJob } = await import('../services/jobs.js');
    res.json(await reviseJob(String(req.params.id), req.ownerId!, String(req.body?.note || '')));
  } catch (e: any) { res.status(e.status || 500).json({ error: e.message }); }
});

// SSE progress stream: reconnect recovers persisted status (replays from afterId).
// EventSource cannot send headers, so `?token=` is accepted as a fallback
// (same JWT, verified identically). Polling GET /:id/job-events works too.
r.get('/:id/events', async (req, res) => {
  let owner: string | null = null;
  const h = req.headers.authorization || '';
  const m = h.match(/^Bearer (.+)$/);
  if (m) {
    try { owner = verifyToken(m[1]).id; } catch { /* fall through to query token */ }
  }
  if (!owner && typeof req.query.token === 'string' && req.query.token) {
    try { owner = verifyToken(req.query.token).id; } catch { /* unauthorized below */ }
  }
  if (!owner) { res.status(401).json({ error: 'Missing bearer token' }); return; }
  const j = await getJob(String(req.params.id));
  if (!j || (j as any).owner_id !== owner) { res.status(404).json({ error: 'Not found' }); return; }
  res.writeHead(200, {
    'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive',
    'Access-Control-Allow-Origin': '*',
  });
  let after = Number(req.query.after || 0);
  let alive = true;
  req.on('close', () => { alive = false; });
  // Initial snapshot so refresh recovers status immediately.
  res.write(`event: snapshot\ndata: ${JSON.stringify(j)}\n\n`);
  while (alive) {
    const evs = await getEvents(String(req.params.id), after);
    for (const e of evs) {
      // Never leak credentials/internal reasoning: only readable kind+message.
      res.write(`data: ${JSON.stringify({ id: e.id, kind: e.kind, message: e.message, stage: e.stage, status: e.status, created_at: e.created_at })}\n\n`);
      after = e.id;
    }
    const cur = await getJob(String(req.params.id));
    if (cur && ['published', 'failed', 'cancelled', 'done', 'awaiting-approval', 'blocked-no-evidence'].includes((cur as any).status)) {
      const rest = await getEvents(String(req.params.id), after);
      for (const e of rest) res.write(`data: ${JSON.stringify({ id: e.id, kind: e.kind, message: e.message })}\n\n`);
      res.write(`event: end\ndata: ${JSON.stringify(cur)}\n\n`);
      res.end();
      return;
    }
    await new Promise((rr) => setTimeout(rr, 1500));
  }
});

r.get('/:id/job-events', requireAuth, async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!j || (j as any).owner_id !== req.ownerId) { res.status(404).json({ error: 'Not found' }); return; }
  res.json(await getEvents(String(req.params.id), Number(req.query.after || 0)));
});

// ---- worker-internal endpoints (service token) ----
r.post('/internal/next', async (req, res) => {
  const { worker_id } = req.body || {};
  if (!worker_id) { res.status(400).json({ error: 'worker_id required' }); return; }
  res.json({ job: await claimNextJob(String(worker_id)) });
});

r.post('/internal/:id/heartbeat', async (req, res) => {
  try { await heartbeat(String(req.params.id), String(req.body?.worker_id || ''), req.body || {}); res.json({ ok: true }); }
  catch (e: any) { res.status(e.status || 500).json({ error: e.message }); }
});

r.post('/internal/:id/progress', async (req, res) => {
  const { status, stage, kind, message, data, error, cost_usd, model_calls } = req.body || {};
  if (kind || message) await addEvent(String(req.params.id), String(kind || 'progress'), String(message || kind), stage || '', status || '', data || {});
  await updateJobProgress(String(req.params.id), { status, stage, error, cost_usd, model_calls });
  res.json({ ok: true });
});

r.post('/internal/:id/artifacts', async (req, res) => {
  const { name, path: p, content_type, size_bytes, sha256 } = req.body || {};
  if (!name || !p) { res.status(400).json({ error: 'name + path required (artifact refs, not blobs)' }); return; }
  await saveArtifact(String(req.params.id), name, p, content_type || '', size_bytes || 0, sha256 || '');
  res.json({ ok: true });
});

r.get('/internal/:id/artifacts-list', async (req, res) => {
  res.json(await listArtifacts(String(req.params.id)));
});

export default r;
