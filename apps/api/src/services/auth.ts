import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import { getDb, newId, nowIso } from '../db.js';

const JWT_SECRET = () => process.env.JWT_SECRET || 'dev-secret-change-me';
const TOKEN_DAYS = 30;

export interface AuthUser { id: string; email: string; }

export async function register(email: string, password: string): Promise<{ user: AuthUser; token: string }> {
  email = email.toLowerCase().trim();
  if (!email.includes('@')) throw Object.assign(new Error('Invalid email'), { status: 400 });
  if (password.length < 8) throw Object.assign(new Error('Password min 8 chars'), { status: 400 });
  const db = await getDb();
  const { rows } = await db.query('SELECT id FROM users WHERE email = ?', [email]);
  if (rows.length) throw Object.assign(new Error('Email already registered'), { status: 409 });
  const id = newId('u');
  const hash = await bcrypt.hash(password, 10);
  await db.query('INSERT INTO users(id, email, password_hash, created_at) VALUES (?, ?, ?, ?)', [id, email, hash, nowIso()]);
  return { user: { id, email }, token: sign(id, email) };
}

export async function login(email: string, password: string): Promise<{ user: AuthUser; token: string }> {
  email = email.toLowerCase().trim();
  const db = await getDb();
  const { rows } = await db.query('SELECT id, email, password_hash FROM users WHERE email = ?', [email]);
  if (!rows.length) throw Object.assign(new Error('Invalid credentials'), { status: 401 });
  const ok = await bcrypt.compare(password, rows[0].password_hash);
  if (!ok) throw Object.assign(new Error('Invalid credentials'), { status: 401 });
  return { user: { id: rows[0].id, email: rows[0].email }, token: sign(rows[0].id, rows[0].email) };
}

function sign(id: string, email: string): string {
  return jwt.sign({ sub: id, email }, JWT_SECRET(), { expiresIn: `${TOKEN_DAYS}d` });
}

export function verifyToken(token: string): AuthUser {
  const p = jwt.verify(token, JWT_SECRET()) as any;
  return { id: p.sub, email: p.email };
}
