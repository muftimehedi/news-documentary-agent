// Express entrypoint. Owns auth, prefs, chat/jobs API, accounts,
// downloads, publishing. Python worker owns agent execution via
// /api/jobs/internal/* (service token) — never OAuth tokens.
import cors from 'cors';
import dotenv from 'dotenv';
import express from 'express';
import helmet from 'helmet';
import path from 'node:path';

dotenv.config({ path: path.resolve(process.cwd(), '../../.env') });
dotenv.config();

import { migrate } from './db.js';
import accounts from './routes/accounts.js';
import artifacts from './routes/artifacts.js';
import auth from './routes/auth.js';
import chat from './routes/chat.js';
import jobs from './routes/jobs.js';
import prefs from './routes/prefs.js';
import publish from './routes/publish.js';
import social from './routes/social.js';

const app = express();
app.use(helmet({ contentSecurityPolicy: false, crossOriginEmbedderPolicy: false }));
app.use(cors());
app.use(express.json({ limit: '2mb' }));

app.get('/api/health', (_req, res) => res.json({
  ok: true, contracts: 'v1', time: new Date().toISOString(),
  db: process.env.DATABASE_URL ? 'postgres' : 'sqlite-fallback',
  queue: 'sql-jobs-table (Node + Python compatible)',
}));
app.use('/api/auth', auth);
app.use('/api/chat', chat);
app.use('/api/jobs', jobs);
app.use('/api/me/preferences', prefs);
app.use('/api/accounts', accounts);
app.use('/api/publish', publish);
app.use('/api/social', social);
app.use('/api', artifacts);

const PORT = Number(process.env.API_PORT || 4000);
migrate().then(({ dialect }) => {
  console.log(`[newsdoc-api] migrations applied (dialect=${dialect})`);
  app.listen(PORT, () => console.log(`[newsdoc-api] listening on :${PORT}`));
}).catch((e) => { console.error('[newsdoc-api] migration failed', e); process.exit(1); });
