// Credential vault: AES-256-GCM encryption with ACCOUNTS_ENCRYPTION_KEY.
// Tokens stay server-side (DB only stores ciphertext). Never sent to LLM,
// logs, frontend, or git. Owner-scoped: every op filters by owner.
import crypto from 'node:crypto';
import { getDb, newId, nowIso } from '../db.js';

function key(): Buffer {
  const raw = process.env.ACCOUNTS_ENCRYPTION_KEY || '';
  if (!raw) throw new Error('ACCOUNTS_ENCRYPTION_KEY not configured');
  // Accept 64-hex or any passphrase (hashed to 32 bytes).
  if (/^[0-9a-fA-F]{64}$/.test(raw)) return Buffer.from(raw, 'hex');
  return crypto.createHash('sha256').update(raw).digest();
}

export function encryptSecret(obj: any): string {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key(), iv);
  const pt = Buffer.from(JSON.stringify(obj), 'utf8');
  const ct = Buffer.concat([cipher.update(pt), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, tag, ct]).toString('base64');
}

export function decryptSecret(blob: string): any {
  const buf = Buffer.from(blob, 'base64');
  const iv = buf.subarray(0, 12);
  const tag = buf.subarray(12, 28);
  const ct = buf.subarray(28);
  const decipher = crypto.createDecipheriv('aes-256-gcm', key(), iv);
  decipher.setAuthTag(tag);
  const pt = Buffer.concat([decipher.update(ct), decipher.final()]);
  return JSON.parse(pt.toString('utf8'));
}

export function fingerprint(secret: any): string {
  for (const v of Object.values(secret || {})) {
    if (typeof v === 'string' && v.length >= 8) return `…${v.slice(-4)}`;
  }
  return '…n/a';
}

export function redact(obj: any): any {
  if (Array.isArray(obj)) return obj.map(redact);
  if (obj && typeof obj === 'object') {
    const out: any = {};
    for (const [k, v] of Object.entries(obj)) {
      if (/token|secret|password|key|auth|credential/i.test(k)) out[k] = '[redacted]';
      else out[k] = redact(v);
    }
    return out;
  }
  return obj;
}

// Accounts table is shared with the Python vault (columns: id, owner, platform,
// label, status, public_meta). The secret ciphertext lives in a sidecar table
// owned by Express so Python's schema stays untouched.
async function ensureSecretTable() {
  const db = await getDb();
  await db.execScript(`CREATE TABLE IF NOT EXISTS account_secrets(account_id TEXT PRIMARY KEY, ciphertext TEXT NOT NULL, updated_at TEXT NOT NULL);`);
}

export async function connectAccount(owner: string, platform: string, label: string, secret: any, publicMeta: any) {
  const db = await getDb();
  await ensureSecretTable();
  const ciphertext = encryptSecret(secret); // throws before any row is stored
  const id = `${platform}-${Math.random().toString(36).slice(2, 10)}`;
  const now = nowIso();
  await db.query(
    `INSERT INTO accounts(id, owner, platform, label, status, public_meta, created_at, updated_at) VALUES (?, ?, ?, ?, 'connected', ?, ?, ?)`,
    [id, owner, platform, label, JSON.stringify(publicMeta || {}), now, now],
  );
  await db.query(
    `INSERT INTO account_secrets(account_id, ciphertext, updated_at) VALUES (?, ?, ?)`,
    [id, ciphertext, now],
  );
  return { id, platform, label, status: 'connected', credential: fingerprint(secret), public_meta: publicMeta || {} };
}

export async function listAccounts(owner: string) {
  const db = await getDb();
  const { rows } = await db.query('SELECT id, platform, label, status, public_meta, created_at FROM accounts WHERE owner = ? ORDER BY created_at DESC', [owner]);
  return rows.map((r: any) => ({ ...r, public_meta: safeJson(r.public_meta) }));
}

export async function getAccount(owner: string, id: string) {
  const db = await getDb();
  const { rows } = await db.query('SELECT id, platform, label, status, public_meta FROM accounts WHERE id = ? AND owner = ?', [id, owner]);
  if (!rows.length) return null;
  return { ...rows[0], public_meta: safeJson(rows[0].public_meta) };
}

export async function loadSecret(owner: string, id: string): Promise<any> {
  const db = await getDb();
  await ensureSecretTable();
  const acc = await getAccount(owner, id);
  if (!acc || acc.status !== 'connected') throw Object.assign(new Error('Account not connected'), { status: 409 });
  const { rows } = await db.query('SELECT ciphertext FROM account_secrets WHERE account_id = ?', [id]);
  if (!rows.length) throw Object.assign(new Error('Credential missing (disconnected?)'), { status: 410 });
  return decryptSecret(rows[0].ciphertext);
}

export async function disconnectAccount(owner: string, id: string): Promise<boolean> {
  const db = await getDb();
  await ensureSecretTable();
  const acc = await getAccount(owner, id);
  if (!acc) return false;
  await db.query('DELETE FROM account_secrets WHERE account_id = ?', [id]);
  await db.query(`UPDATE accounts SET status='disconnected', updated_at=? WHERE id=? AND owner=?`, [nowIso(), id, owner]);
  return true;
}

function safeJson(s: string) { try { return JSON.parse(s || '{}'); } catch { return {}; } }
export { newId };
