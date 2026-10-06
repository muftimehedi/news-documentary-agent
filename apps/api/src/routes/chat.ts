import { Router } from 'express';
import { getDb, nowIso, newId } from '../db.js';
import { requireAuth, type AuthedRequest } from '../middleware/auth.js';
import { createJob } from '../services/jobs.js';

const r = Router();
r.use(requireAuth);

// List/create threads
r.get('/threads', async (req: AuthedRequest, res) => {
  const db = await getDb();
  const { rows } = await db.query('SELECT * FROM chat_threads WHERE owner = ? ORDER BY updated_at DESC LIMIT 50', [req.ownerId]);
  res.json(rows);
});

r.post('/threads', async (req: AuthedRequest, res) => {
  const db = await getDb();
  const thread_id = (req.body?.thread_id as string) || newId('thread');
  const now = nowIso();
  await db.query(
    `INSERT INTO chat_threads(thread_id, owner, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(thread_id) DO UPDATE SET updated_at=excluded.updated_at`,
    [thread_id, req.ownerId, String(req.body?.title || thread_id).slice(0, 120), now, now],
  );
  res.status(201).json({ thread_id });
});

r.get('/threads/:id', async (req: AuthedRequest, res) => {
  const db = await getDb();
  const { rows } = await db.query('SELECT * FROM chat_messages WHERE thread_id = ? AND owner = ? ORDER BY id ASC LIMIT 500', [String(req.params.id), req.ownerId]);
  res.json(rows);
});

// Chat with the Main Deep Agent (via shared services).
// Documentary requests create a production job on the same backend the browser uses.
r.post('/threads/:id/messages', async (req: AuthedRequest, res) => {
  const db = await getDb();
  const thread_id = String(req.params.id);
  const content = String(req.body?.content || '').slice(0, 4000);
  if (!content) { res.status(400).json({ error: 'content required' }); return; }
  const now = nowIso();
  await db.query(
    `INSERT INTO chat_threads(thread_id, owner, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(thread_id) DO UPDATE SET updated_at=excluded.updated_at`,
    [thread_id, req.ownerId, content.slice(0, 80), now, now],
  );
  await db.query(
    `INSERT INTO chat_messages(thread_id, owner, role, content, created_at) VALUES (?, ?, 'user', ?, ?)`,
    [thread_id, req.ownerId, content, now],
  );
  const m = content.toLowerCase();
  const wantsDoc = /(report|pdf|document|post|social|thread|publish|produce|create|make|bengali|news)/.test(m) && content.trim().split(/\s+/).length >= 2;
  if (wantsDoc) {
    // Extract a topic: strip command verbs.
    const topic = content.replace(/^(please\s+)?(create|make|produce|generate|write|draft)\s+(a\s+|an\s+)?(report|pdf|document|post|thread|summary)\s+(about|on)?\s*/i, '').trim() || content;
    const settings = req.body?.settings || {};
    const job_type = settings.job_type === 'social' ? 'social' : 'report';
    const job = await createJob(req.ownerId!, topic.slice(0, 200), { ...(settings || {}), topic: topic.slice(0, 200), job_type }, thread_id) as any;
    const reply = job_type === 'social'
      ? `On it — social-post job ${job.job_id} queued for "${job.topic}". I'll research, fact-check and draft per-platform texts (X/Facebook/Hikmah + manual YouTube copy). Review, edit and publish them from the job page. Closing this tab won't cancel it.`
      : `On it — PDF report job ${job.job_id} queued for "${job.topic}". I'll research, fact-check, write and render the report with source links. Preview it on the job page and request revisions any time. Closing this tab won't cancel it.`;
    await db.query(`INSERT INTO chat_messages(thread_id, owner, role, content, job_id, created_at) VALUES (?, ?, 'agent', ?, ?, ?)`, [thread_id, req.ownerId, reply, job.job_id, nowIso()]);
    res.json({ reply, job_id: job.job_id, job });
    return;
  }
  const reply = `Got it. Tell me a topic ("research a report on ..." or "draft social posts about ...") and I'll research, verify and write it — or use the New output form for settings (report/social, language, platforms). English by default; Bengali ("bn") supported.`;
  await db.query(`INSERT INTO chat_messages(thread_id, owner, role, content, created_at) VALUES (?, ?, 'agent', ?, ?)`, [thread_id, req.ownerId, reply, nowIso()]);
  res.json({ reply, job_id: null });
});

export default r;
