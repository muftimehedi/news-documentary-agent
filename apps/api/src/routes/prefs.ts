import { Router } from 'express';
import { getDb } from '../db.js';
import { requireAuth, type AuthedRequest } from '../middleware/auth.js';

const r = Router();
r.use(requireAuth);

r.get('/', async (req: AuthedRequest, res) => {
  const db = await getDb();
  const { rows } = await db.query('SELECT key, value FROM preferences WHERE owner = ?', [req.ownerId]);
  const out: any = { language: 'en' };
  for (const row of rows) { try { out[row.key] = JSON.parse(row.value); } catch { out[row.key] = row.value; } }
  res.json(out);
});

r.put('/', async (req: AuthedRequest, res) => {
  const db = await getDb();
  const body = req.body || {};
  for (const [k, v] of Object.entries(body).slice(0, 50)) {
    await db.query(
      `INSERT INTO preferences(owner, key, value) VALUES (?, ?, ?)
       ON CONFLICT(owner, key) DO UPDATE SET value=excluded.value`,
      [req.ownerId, String(k).slice(0, 64), JSON.stringify(v)],
    );
  }
  res.json({ ok: true });
});

export default r;
