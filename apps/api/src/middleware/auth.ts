import type { NextFunction, Request, Response } from 'express';
import { verifyToken } from '../services/auth.js';

export interface AuthedRequest extends Request {
  user?: { id: string; email: string };
  ownerId?: string;
}

// Owner = authenticated user id. All rows filtered by owner (authorization).
export function requireAuth(req: AuthedRequest, res: Response, next: NextFunction) {
  const h = req.headers.authorization || '';
  const m = h.match(/^Bearer (.+)$/);
  if (!m) { res.status(401).json({ error: 'Missing bearer token' }); return; }
  try {
    const u = verifyToken(m[1]);
    req.user = u;
    req.ownerId = u.id;
    next();
  } catch {
    res.status(401).json({ error: 'Invalid token' });
  }
}

// Service token for Python worker internal calls (leases, progress writes).
export function requireService(req: Request, res: Response, next: NextFunction) {
  const want = process.env.WORKER_SERVICE_TOKEN || '';
  const got = (req.headers['x-service-token'] as string) || '';
  if (!want) { res.status(500).json({ error: 'WORKER_SERVICE_TOKEN not configured' }); return; }
  if (got !== want) { res.status(403).json({ error: 'Bad service token' }); return; }
  next();
}
