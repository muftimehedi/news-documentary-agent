// Database owner: Express API. Single migration system for shared tables.
// Uses PostgreSQL when DATABASE_URL is set, else node:sqlite fallback (dev).
// Python worker never runs DDL in shared mode; it only reads/writes rows
// via the HTTP API (service token) or direct read-only row access.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export type DbDialect = 'pg' | 'sqlite';

export interface Db {
  dialect: DbDialect;
  query<T = any>(sql: string, params?: any[]): Promise<{ rows: T[] }>;
  execScript(sql: string): Promise<void>;
  close(): Promise<void>;
}

let instance: Db | null = null;

function pgSql(sql: string): string {
  // Translate sqlite AUTOINCREMENT DDL to Postgres + ? placeholders handled by caller.
  return sql
    .replace(/INTEGER PRIMARY KEY AUTOINCREMENT/gi, 'SERIAL PRIMARY KEY')
    .replace(/IF NOT EXISTS idx_/g, 'IF NOT EXISTS idx_');
}

export async function getDb(): Promise<Db> {
  if (instance) return instance;
  const url = process.env.DATABASE_URL || '';
  if (url) {
    const { Pool } = await import('pg');
    const pool = new Pool({ connectionString: url });
    instance = {
      dialect: 'pg',
      async query(sql, params = []) {
        // Convert ? to $n
        let i = 0;
        const text = sql.replace(/\?/g, () => `$${++i}`);
        const r = await pool.query(text, params);
        return { rows: r.rows as any[] };
      },
      async execScript(sql: string) {
        const statements = splitStatements(pgSql(sql));
        for (const s of statements) {
          if (s.trim()) await pool.query(s);
        }
      },
      async close() { await pool.end(); },
    };
    return instance;
  }
  // sqlite fallback via node:sqlite (Node >= 22)
  const mod: any = await import('node:sqlite').catch(() => null);
  if (!mod?.DatabaseSync) throw new Error('No DATABASE_URL and node:sqlite unavailable (need Node >= 22).');
  const dbPath = process.env.DB_PATH || 'data/newsdoc.sqlite';
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const dbo = new mod.DatabaseSync(dbPath);
  dbo.exec('PRAGMA journal_mode=WAL');
  instance = {
    dialect: 'sqlite',
    async query(sql, params = []) {
      const up = sql.trim().toUpperCase();
      if (up.startsWith('SELECT') || up.startsWith('WITH') || up.startsWith('RETURNING')) {
        const stmt = dbo.prepare(sql);
        return { rows: stmt.all(...params) as any[] };
      }
      // Support RETURNING emulation: node:sqlite supports RETURNING directly.
      const stmt = dbo.prepare(sql);
      try {
        const rows = stmt.all(...params) as any[];
        return { rows };
      } catch {
        stmt.run(...params);
        return { rows: [] };
      }
    },
    async execScript(sql: string) {
      dbo.exec(sql);
    },
    async close() { dbo.close(); },
  };
  return instance;
}

function splitStatements(sql: string): string[] {
  return sql.split(/;\s*\n/).map((s) => s.trim()).filter(Boolean).map((s) => s + ';');
}

export async function migrate(): Promise<{ dialect: DbDialect }> {
  const db = await getDb();
  const here = path.dirname(fileURLToPath(import.meta.url));
  const migDir = path.resolve(here, '../migrations');
  const files = fs.readdirSync(migDir).filter((f) => f.endsWith('.sql')).sort();
  await db.execScript(`CREATE TABLE IF NOT EXISTS schema_migrations(filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL);`);
  for (const f of files) {
    const { rows } = await db.query('SELECT filename FROM schema_migrations WHERE filename = ?', [f]);
    if (rows.length) continue;
    let sql = fs.readFileSync(path.join(migDir, f), 'utf8');
    if (db.dialect === 'pg') sql = pgSql(sql);
    await db.execScript(sql);
    await db.query('INSERT INTO schema_migrations(filename, applied_at) VALUES (?, ?)', [f, new Date().toISOString()]);
  }
  return { dialect: db.dialect };
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function newId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}
