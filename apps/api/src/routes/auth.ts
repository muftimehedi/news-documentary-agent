import { Router } from 'express';
import { login, register } from '../services/auth.js';

const r = Router();
r.post('/register', async (req, res) => {
  try {
    const { email, password } = req.body || {};
    const out = await register(String(email || ''), String(password || ''));
    res.json(out);
  } catch (e: any) { res.status(e.status || 500).json({ error: e.message }); }
});
r.post('/login', async (req, res) => {
  try {
    const { email, password } = req.body || {};
    const out = await login(String(email || ''), String(password || ''));
    res.json(out);
  } catch (e: any) { res.status(e.status || 500).json({ error: e.message }); }
});
export default r;
