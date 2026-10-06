// Authorized artifact downloads (ownership-enforced) + manual ZIP bundle.
// No account needed: MP4 + thumbnail + subtitles + title/description +
// platform captions + source links + required attribution.
import { Router } from 'express';
import archiver from 'archiver';
import fs from 'node:fs';
import path from 'node:path';
import { requireAuth, type AuthedRequest } from '../middleware/auth.js';
import { getJob, listArtifacts } from '../services/jobs.js';
import { defaultMeta, jobDir } from '../services/publishing.js';

const r = Router();

// <video>, <track> and poster <img> cannot send Authorization headers, so an
// equivalent `?token=` query param is accepted (same JWT, verified identically
// by requireAuth). Fetch-based downloads keep using the header.
function tokenQueryToHeader(req: any, _res: any, next: any) {
  if (!req.headers.authorization && typeof req.query?.token === 'string' && req.query.token) {
    req.headers.authorization = `Bearer ${req.query.token}`;
  }
  next();
}
r.use(tokenQueryToHeader);
r.use(requireAuth);

const SAFE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,64}$/;

r.get('/jobs/:id/artifacts', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!j || (j as any).owner_id !== req.ownerId) { res.status(404).json({ error: 'Not found' }); return; }
  const rows = await listArtifacts(String(req.params.id));
  const dir = jobDir(String(req.params.id));
  // Union DB refs + well-known files on disk (worker writes files first).
  const known = ['report.pdf', 'report.md', 'posts.json', 'social_meta.json',
    'documentary.mp4', 'thumbnail.jpg', 'captions.srt', 'captions.vtt', 'script.json',
    'sources.json', 'fact_report.json', 'review.json', 'research_notes.json',
    'render_manifest.json', 'manual_metadata.txt'];
  const seen = new Set(rows.map((a: any) => a.name));
  const out = [...rows];
  for (const f of known) {
    if (fs.existsSync(path.join(dir, f)) && ![...seen].some((s) => String(s).includes(f))) {
      const st = fs.statSync(path.join(dir, f));
      out.push({ job_id: String(req.params.id), name: f, path: f, content_type: guessType(f), size_bytes: st.size });
    }
  }
  res.json(out);
});

r.get('/jobs/:id/artifacts/:name', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!j || (j as any).owner_id !== req.ownerId) { res.status(404).json({ error: 'Not found' }); return; }
  const name = String(req.params.name);
  if (!SAFE.test(name) || name.includes('..')) { res.status(400).json({ error: 'Bad artifact name' }); return; }
  const dir = path.resolve(jobDir(String(req.params.id)));
  const target = path.resolve(dir, name);
  if (target !== dir && !target.startsWith(dir + path.sep)) { res.status(400).json({ error: 'Unsafe path' }); return; }
  if (!fs.existsSync(target)) { res.status(404).json({ error: 'Artifact not found (job may still be running)' }); return; }
  const type = guessType(name);
  // Previewable media streams inline so <video> can play it; everything else
  // keeps the attachment disposition for direct-link downloads.
  res.setHeader('Content-Disposition',
    /^(video|image|audio)\//.test(type) || name.endsWith('.vtt') || name.endsWith('.pdf')
      ? 'inline' : `attachment; filename="${String(req.params.id)}_${name}"`);
  sendFileWithRanges(req, res, target, type);
});

// Browser subtitles: the downloadable SRT stays untouched; this endpoint
// serves the same cues converted to WebVTT for <track> playback.
r.get('/jobs/:id/captions.vtt', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!j || (j as any).owner_id !== req.ownerId) { res.status(404).json({ error: 'Not found' }); return; }
  const srt = path.join(jobDir(String(req.params.id)), 'captions.srt');
  if (!fs.existsSync(srt)) { res.status(404).json({ error: 'Subtitles not ready yet (job may still be running)' }); return; }
  res.setHeader('Content-Type', 'text/vtt; charset=utf-8');
  res.setHeader('Content-Disposition', 'inline');
  res.send(srtToVtt(fs.readFileSync(srt, 'utf8')));
});

// HTTP byte-range support: browsers seek with `Range: bytes=...` and must get
// 206 Partial Content without downloading the whole file first.
function sendFileWithRanges(req: any, res: any, target: string, contentType: string) {
  const total = fs.statSync(target).size;
  res.setHeader('Content-Type', contentType);
  res.setHeader('Accept-Ranges', 'bytes');
  const range = req.headers.range as string | undefined;
  if (!range) {
    res.setHeader('Content-Length', String(total));
    fs.createReadStream(target).pipe(res);
    return;
  }
  const m = range.match(/^bytes=(\d*)-(\d*)$/);
  let start = NaN, end = NaN;
  if (m) {
    start = m[1] === '' ? NaN : parseInt(m[1], 10);
    end = m[2] === '' ? NaN : parseInt(m[2], 10);
  }
  if (m && isNaN(start) && !isNaN(end)) {
    // Suffix range: last `end` bytes.
    start = Math.max(0, total - end);
    end = total - 1;
  } else if (m && !isNaN(start)) {
    if (isNaN(end) || end >= total) end = total - 1;
  }
  if (!m || isNaN(start) || isNaN(end) || start >= total || start > end) {
    res.status(416);
    res.setHeader('Content-Range', `bytes */${total}`);
    res.end();
    return;
  }
  res.status(206);
  res.setHeader('Content-Range', `bytes ${start}-${end}/${total}`);
  res.setHeader('Content-Length', String(end - start + 1));
  fs.createReadStream(target, { start, end }).pipe(res);
}

export function srtToVtt(srt: string): string {
  const body = srt
    .replace(/\r/g, '')
    .split('\n')
    .map((l) => (l.includes('-->') ? l.replace(/(\d{2}:\d{2}:\d{2}),(\d{3})/g, '$1.$2') : l))
    .join('\n')
    .replace(/^\n+/, '');
  return `WEBVTT\n\n${body}`;
}

r.get('/jobs/:id/bundle.zip', async (req: AuthedRequest, res) => {
  const j = await getJob(String(req.params.id));
  if (!j || (j as any).owner_id !== req.ownerId) { res.status(404).json({ error: 'Not found' }); return; }
  const dir = jobDir(String(req.params.id));
  const video = path.join(dir, 'documentary.mp4');
  const pdf = path.join(dir, 'report.pdf');
  const hasVideo = fs.existsSync(video);
  const hasPdf = fs.existsSync(pdf);
  if (!hasVideo && !hasPdf) { res.status(404).json({ error: 'No finished output yet' }); return; }
  const meta = defaultMeta(String(req.params.id));
  const captions = readText(path.join(dir, 'captions.srt'));
  const sources = readJson(path.join(dir, 'sources.json'), []);
  const provenance = readJson(path.join(dir, 'render_manifest.json'), null);
  const metadataTxt = [
    'TITLE', meta.title, '', 'DESCRIPTION', meta.description, '',
    'CAPTIONS (plain text)', srtToText(captions), '',
    'SOURCE LINKS', ...(sources.map((s: any) => `- ${s?.url || ''} (${s?.publisher || ''})`) || []),
    '', 'REQUIRED ATTRIBUTION', 'Generated illustrations are synthetic reconstructions, not authentic news footage.',
    provenance ? `RENDER MANIFEST: ${JSON.stringify(provenance).slice(0, 2000)}` : '',
  ].join('\n');
  fs.writeFileSync(path.join(dir, 'manual_metadata.txt'), metadataTxt);
  res.setHeader('Content-Type', 'application/zip');
  res.setHeader('Content-Disposition', `attachment; filename="${String(req.params.id)}_bundle.zip"`);
  const archive = archiver('zip', { zlib: { level: 6 } });
  archive.pipe(res);
  // Doc outputs (active scope) + legacy video files when present (history).
  for (const f of ['report.pdf', 'report.md', 'posts.json', 'sources.json', 'fact_report.json',
                   'documentary.mp4', 'thumbnail.jpg', 'captions.srt', 'manual_metadata.txt']) {
    if (fs.existsSync(path.join(dir, f))) archive.file(path.join(dir, f), { name: `${String(req.params.id)}_${f}` });
  }
  await archive.finalize();
});

function guessType(name: string): string {
  if (name.endsWith('.mp4')) return 'video/mp4';
  if (name.endsWith('.jpg')) return 'image/jpeg';
  if (name.endsWith('.png')) return 'image/png';
  if (name.endsWith('.pdf')) return 'application/pdf';
  if (name.endsWith('.md')) return 'text/markdown';
  if (name.endsWith('.srt')) return 'text/plain';
  if (name.endsWith('.json')) return 'application/json';
  if (name.endsWith('.txt')) return 'text/plain';
  if (name.endsWith('.wav')) return 'audio/wav';
  return 'application/octet-stream';
}

function readText(p: string): string { try { return fs.readFileSync(p, 'utf8'); } catch { return ''; } }
function readJson(p: string, fb: any): any { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return fb; } }
function srtToText(srt: string): string {
  return srt.split('\n').map((l) => l.trim()).filter((l) => l && !/^\d+$/.test(l) && !l.includes('-->')).join('\n');
}

export default r;
