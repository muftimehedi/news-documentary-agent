import { Router } from 'express';
import { requireAuth, type AuthedRequest } from '../middleware/auth.js';
import { connectAccount, disconnectAccount, getAccount, listAccounts, redact } from '../services/vault.js';
import { getAdapter, integrationLabel } from '../services/adapters.js';

const r = Router();
r.use(requireAuth);

r.get('/', async (req: AuthedRequest, res) => {
  const accs = await listAccounts(req.ownerId!);
  res.json(accs.map((a: any) => ({ ...a, integration: integrationLabel(a.platform) })));
});

r.post('/connect', async (req: AuthedRequest, res) => {
  try {
    const { platform, label, secret } = req.body || {};
    if (!platform || !secret) { res.status(400).json({ error: 'platform + secret required' }); return; }
    // Verify without storing: wrong credentials store nothing.
    const info = await getAdapter(platform).verify(secret);
    const acc = await connectAccount(req.ownerId!, platform, String(label || `my-${platform}`), secret, info);
    // Connecting never publishes — no publish path runs here.
    res.status(201).json({ ...acc, public_meta: info, note: 'Connected. Nothing was published.' });
  } catch (e: any) { res.status(e.permanent ? 422 : 502).json({ error: String(e.message).slice(0, 400), redacted: redact(req.body?.secret || {}) && undefined }); }
});

r.delete('/:id', async (req: AuthedRequest, res) => {
  const ok = await disconnectAccount(req.ownerId!, String(req.params.id));
  if (!ok) { res.status(404).json({ error: 'Not found' }); return; }
  res.json({ ok: true, note: 'Disconnected. Stored secret deleted; it cannot publish.' });
});

r.get('/:id', async (req: AuthedRequest, res) => {
  const a = await getAccount(req.ownerId!, String(req.params.id));
  if (!a) { res.status(404).json({ error: 'Not found' }); return; }
  res.json({ ...a, integration: integrationLabel(a.platform) });
});

export default r;
