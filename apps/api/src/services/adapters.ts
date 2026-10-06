// Publishing adapters (TypeScript mirror of Python adapters).
// Real integration / fixture / unconfigured / unsupported are labeled explicitly.
// A fake receipt is never evidence of a real upload: fixture receipts carry
// status 'succeeded-fixture' and fixture:true.
import crypto from 'node:crypto';
import fs from 'node:fs';

export interface UploadReceipt {
  destination: string;
  remote_id: string;
  url: string;
  visibility: string;
  status: string;
  timestamp: string;
  fixture: boolean;
  note?: string;
}

export class AdapterError extends Error {
  permanent: boolean;
  constructor(message: string, permanent = false) { super(message); this.permanent = permanent; }
}

async function fileSizeMb(p: string): Promise<number> {
  return fs.statSync(p).size / (1024 * 1024);
}

export const adapters: Record<string, {
  display: string; mode: 'real' | 'fixture'; setupHelp: string;
  verify(creds: any): Promise<any>;
  validate(video: string, title: string, desc: string, visibility: string): Promise<string[]>;
  upload(video: string, title: string, desc: string, visibility: string, creds: any): Promise<UploadReceipt>;
  /** Text-post support (doc scope). Absent = reuse of video adapters is refused. */
  validateText?(text: string): Promise<string[]>;
  postText?(text: string, creds: any): Promise<UploadReceipt>;
}> = {
  youtube: {
    display: 'YouTube', mode: 'real',
    setupHelp: 'Google Cloud → YouTube Data API v3 → OAuth Desktop client → connect via CLI `newsdoc auth-youtube` or paste token. Scope: youtube.upload. Text posts: NOT supported — the Data API has no community/text-post endpoint (video upload + comments only); generated title/description are for manual use.',
    // NOTE: no validateText/postText here by design. The social publish flow
    // refuses platforms without postText instead of reusing video upload.
    async verify(creds: any) {
      const tf = creds?.token_file || creds?.tokenFile;
      if (!tf || !fs.existsSync(tf)) throw new AdapterError('YouTube token missing. Run `newsdoc auth-youtube --account LABEL` first.', true);
      // Offline verify: token file parses. Live channel lookup happens at upload.
      try { JSON.parse(fs.readFileSync(tf, 'utf8')); } catch { throw new AdapterError('YouTube token file unreadable.', true); }
      return { account: creds?.channel_title || 'YouTube channel' };
    },
    async validate(video, title, desc, visibility) {
      const errs: string[] = [];
      if (!/\.(mp4|mov)$/i.test(video)) errs.push('YouTube: need MP4/MOV');
      if (!['unlisted', 'private', 'public'].includes(visibility)) errs.push('YouTube visibility must be unlisted/private/public');
      if (!(title.length >= 1 && title.length <= 100)) errs.push('YouTube title: 1–100 chars');
      if (desc.length > 5000) errs.push('YouTube description: max 5000 chars');
      return errs;
    },
    async upload(video, title, desc, visibility, creds) {
      if (process.env.YOUTUBE_PUBLISH_MODE !== 'real') {
        return fixtureReceipt('youtube', video, visibility, 'YOUTUBE_PUBLISH_MODE != real; no upload performed');
      }
      // Real upload requires googleapis + OAuth token. Keep dependency-free:
      // use direct REST with access token from token_file.
      const tf = creds?.token_file;
      if (!tf || !fs.existsSync(tf)) throw new AdapterError('YouTube token missing (disconnected?).', true);
      const tok = JSON.parse(fs.readFileSync(tf, 'utf8'));
      const access = tok.access_token || tok.token;
      if (!access) throw new AdapterError('YouTube access token unavailable; re-authenticate.', true);
      // Resumable upload: init session then PUT bytes (simplified, documented).
      const init = await fetch('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status', {
        method: 'POST',
        headers: { Authorization: `Bearer ${access}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ snippet: { title: title.slice(0, 100), description: desc.slice(0, 5000), categoryId: '25' }, status: { privacyStatus: visibility, selfDeclaredMadeForKids: false } }),
      });
      if (!init.ok && init.status >= 400 && init.status < 500) {
        throw new AdapterError(`YouTube init failed (${init.status}): ${(await init.text()).slice(0, 300)}`, true);
      }
      if (!init.ok) throw new AdapterError(`YouTube init failed (${init.status})`, false);
      const sessionUrl = init.headers.get('location');
      if (!sessionUrl) throw new AdapterError('YouTube: no resumable session URL', false);
      const buf = fs.readFileSync(video);
      const put = await fetch(sessionUrl, { method: 'PUT', headers: { 'Content-Length': String(buf.length) }, body: buf as any });
      const body: any = await put.json().catch(() => ({}));
      const rid = body?.id || '';
      if (!put.ok || !rid) throw new AdapterError(`YouTube upload failed: ${JSON.stringify(body).slice(0, 300)}`, put.status < 500);
      return { destination: 'youtube', remote_id: rid, url: `https://youtu.be/${rid}`, visibility, status: 'succeeded', timestamp: new Date().toISOString(), fixture: false };
    },
  },
  facebook: {
    display: 'Facebook', mode: 'real',
    setupHelp: 'Meta app + Facebook Login (pages_show_list, pages_read_engagement, pages_manage_posts) → Page access token. Pages only; app review needed for public use.',
    async verify(creds: any) {
      if (!creds?.page_token || !creds?.page_id) throw new AdapterError('Facebook: page_id + page access token required.', true);
      const r = await fetch(`https://graph.facebook.com/v21.0/${creds.page_id}?access_token=${encodeURIComponent(creds.page_token)}`);
      const b: any = await r.json().catch(() => ({}));
      if (!r.ok || b?.error) throw new AdapterError(`Facebook verify: ${b?.error?.message || r.status}`, r.status === 400 || r.status === 401 || r.status === 403);
      return { account: b?.name || creds.page_id, id: b?.id || creds.page_id };
    },
    async validate(video, title, _desc, visibility) {
      const errs: string[] = [];
      if (!/\.(mp4|mov)$/i.test(video)) errs.push('Facebook: need MP4/MOV');
      if ((await fileSizeMb(video)) > 10 * 1024) errs.push('Facebook: max 10GB');
      if (!(title.length >= 1 && title.length <= 255)) errs.push('Facebook title: 1–255 chars');
      if (!['public', 'unlisted', 'private'].includes(visibility)) errs.push('Facebook visibility must be public/unlisted/private');
      return errs;
    },
    async validateText(text: string) {
      const errs: string[] = [];
      if (!text.trim()) errs.push('Facebook: text required');
      if (text.length > 2000) errs.push(`Facebook text: max 2000 chars (got ${text.length})`);
      return errs;
    },
    async postText(text: string, creds: any) {
      const token = creds?.page_token, pageId = creds?.page_id;
      if (!token || !pageId) throw new AdapterError('Facebook account disconnected.', true);
      const r = await fetch(`https://graph.facebook.com/v21.0/${pageId}/feed?access_token=${encodeURIComponent(token)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text.slice(0, 2000) }),
      });
      const b: any = await r.json().catch(() => ({}));
      if (!r.ok || b?.error || !b?.id) throw new AdapterError(`Facebook text post: ${b?.error?.message || JSON.stringify(b).slice(0, 200)}`, r.status === 400 || r.status === 401 || r.status === 403);
      return { destination: 'facebook', remote_id: b.id, url: `https://www.facebook.com/${b.id}`, visibility: 'public', status: 'succeeded', timestamp: new Date().toISOString(), fixture: false };
    },
    async upload(video, title, desc, visibility, creds) {
      const token = creds?.page_token, pageId = creds?.page_id;
      if (!token || !pageId) throw new AdapterError('Facebook account disconnected.', true);
      const size = fs.statSync(video).size;
      const sessR = await fetch(`https://graph.facebook.com/v21.0/app/uploads?access_token=${encodeURIComponent(token)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_name: video.split('/').pop(), file_length: String(size), file_type: 'video/mp4' }),
      });
      const sess: any = await sessR.json().catch(() => ({}));
      if (!sessR.ok || !sess?.id) throw new AdapterError(`Facebook session failed: ${JSON.stringify(sess).slice(0, 200)}`, false);
      const upR = await fetch(`https://graph.facebook.com/v21.0/${sess.id}`, {
        method: 'POST', headers: { Authorization: `OAuth ${token}`, file_offset: '0', 'Content-Type': 'video/mp4' }, body: fs.readFileSync(video) as any,
      });
      const up: any = await upR.json().catch(() => ({}));
      if (!upR.ok || !up?.h) throw new AdapterError(`Facebook transfer failed: ${JSON.stringify(up).slice(0, 200)}`, false);
      const pubR = await fetch(`https://graph.facebook.com/v21.0/${pageId}/videos?access_token=${encodeURIComponent(token)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.slice(0, 255), description: desc, fbuploader_video_file_chunk: up.h }),
      });
      const pub: any = await pubR.json().catch(() => ({}));
      if (!pubR.ok || !pub?.id) throw new AdapterError(`Facebook publish: ${JSON.stringify(pub).slice(0, 200)}`, true);
      return { destination: 'facebook', remote_id: pub.id, url: `https://www.facebook.com/${pub.id}`, visibility, status: 'succeeded', timestamp: new Date().toISOString(), fixture: false };
    },
  },
  x: {
    display: 'X', mode: 'real',
    setupHelp: 'X developer app → OAuth 2.0 user token (tweet.write, media.write). Paste access token; media upload may bill ~$0.010/req.',
    async verify(creds: any) {
      if (!creds?.access_token) throw new AdapterError('X: user access token required.', true);
      const r = await fetch('https://api.x.com/2/users/me', { headers: { Authorization: `Bearer ${creds.access_token}` } });
      const b: any = await r.json().catch(() => ({}));
      if (!r.ok || b?.errors) throw new AdapterError(`X verify: ${JSON.stringify(b).slice(0, 200)}`, true);
      return { account: '@' + (b?.data?.username || '?'), id: b?.data?.id || '' };
    },
    async validate(video, title, desc, _vis) {
      const errs: string[] = [];
      if (!/\.mp4$/i.test(video)) errs.push('X: need MP4');
      const text = `${title} ${desc}`.trim();
      if (text.length > 280) errs.push(`X post text: max 280 chars (got ${text.length})`);
      return errs;
    },
    async validateText(text: string) {
      const errs: string[] = [];
      if (!text.trim()) errs.push('X: text required');
      if (text.length > 280) errs.push(`X post text: max 280 chars (got ${text.length})`);
      return errs;
    },
    async postText(text: string, creds: any) {
      const token = creds?.access_token;
      if (!token) throw new AdapterError('X account disconnected.', true);
      const r = await fetch('https://api.x.com/2/tweets', {
        method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text.slice(0, 280) }),
      });
      const b: any = await r.json().catch(() => ({}));
      const tid = b?.data?.id || '';
      if (!r.ok || b?.errors || !tid) throw new AdapterError(`X text post: ${JSON.stringify(b).slice(0, 200)}`, r.status === 400 || r.status === 401 || r.status === 403);
      return { destination: 'x', remote_id: tid, url: `https://x.com/i/status/${tid}`, visibility: 'public', status: 'succeeded', timestamp: new Date().toISOString(), fixture: false };
    },
    async upload(video, title, desc, visibility, creds) {
      const token = creds?.access_token;
      if (!token) throw new AdapterError('X account disconnected.', true);
      const buf = fs.readFileSync(video);
      const initR = await fetch('https://api.x.com/2/media/upload/initialize', {
        method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ media_type: 'video/mp4', total_bytes: buf.length, media_category: 'tweet_video' }),
      });
      const init: any = await initR.json().catch(() => ({}));
      const mid = init?.data?.id || init?.id;
      if (!initR.ok || !mid) throw new AdapterError(`X INIT failed: ${JSON.stringify(init).slice(0, 200)}`, false);
      // Simplified single-append for small renders; chunked for large.
      const form = new FormData();
      form.append('media', new Blob([buf], { type: 'video/mp4' }), 'video.mp4');
      form.append('segment_index', '0');
      const appR = await fetch(`https://api.x.com/2/media/upload/${mid}/append`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form as any });
      if (!appR.ok) throw new AdapterError(`X APPEND failed (${appR.status})`, false);
      const finR = await fetch(`https://api.x.com/2/media/upload/${mid}/finalize`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
      if (!finR.ok) throw new AdapterError('X FINALIZE failed', false);
      const twR = await fetch('https://api.x.com/2/tweets', {
        method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: `${title} ${desc}`.trim().slice(0, 280), media: { media_ids: [String(mid)] } }),
      });
      const tw: any = await twR.json().catch(() => ({}));
      const tid = tw?.data?.id || '';
      if (!twR.ok || !tid) throw new AdapterError(`X tweet failed: ${JSON.stringify(tw).slice(0, 200)}`, true);
      return { destination: 'x', remote_id: tid, url: `https://x.com/i/status/${tid}`, visibility, status: 'succeeded', timestamp: new Date().toISOString(), fixture: false };
    },
  },
  hikmah: {
    display: 'Hikmah', mode: 'real',
    setupHelp: 'Hikmah has no public OAuth (verified in hikmah-web source: no OAuth needed). Paste instance base URL + Sanctum personal API token. POST /api/posts type=video, max 1 video/100MB, content ≤20000 chars.',
    async verify(creds: any) {
      const base = (creds?.base_url || '').replace(/\/$/, '');
      if (!base || !creds?.token) throw new AdapterError('Hikmah: base URL + API token required.', true);
      const r = await fetch(`${base}/api/user/me`, { headers: { Authorization: `Bearer ${creds.token}`, Accept: 'application/json' } });
      const b: any = await r.json().catch(() => ({}));
      if (!r.ok) throw new AdapterError(`Hikmah verify (${r.status}): ${JSON.stringify(b).slice(0, 200)}`, r.status === 401 || r.status === 403);
      const d = b?.data || b;
      return { account: d?.user_name || d?.name || d?.email || 'Hikmah user' };
    },
    async validate(video, title, desc, visibility) {
      const errs: string[] = [];
      if (!/\.(flv|mp4|wmv|3gp|mov|avi|ts)$/i.test(video)) errs.push('Hikmah: video must be flv/mp4/wmv/3gp/mov/avi/ts');
      if ((await fileSizeMb(video)) > 100) errs.push('Hikmah: max 100MB/video');
      if (`${title}\n\n${desc}`.length > 20000) errs.push('Hikmah content: max 20000 chars');
      if (!['public', 'unlisted', 'private'].includes(visibility)) errs.push('Hikmah visibility: public/unlisted/private');
      return errs;
    },
    async validateText(text: string) {
      // Text-post shape mirrors the verified video-post API (POST /api/posts);
      // text-type acceptance is live-unverified — failures surface, never faked.
      const errs: string[] = [];
      if (!text.trim()) errs.push('Hikmah: content required');
      if (text.length > 20000) errs.push('Hikmah content: max 20000 chars');
      return errs;
    },
    async postText(text: string, creds: any) {
      const base = (creds?.base_url || '').replace(/\/$/, '');
      if (!base || !creds?.token) throw new AdapterError('Hikmah account disconnected.', true);
      const form = new FormData();
      form.append('type', 'text');
      form.append('content', text.slice(0, 20000));
      form.append('privacy', '1');
      const r = await fetch(`${base}/api/posts`, { method: 'POST', headers: { Authorization: `Bearer ${creds.token}`, Accept: 'application/json' }, body: form as any });
      const b: any = await r.json().catch(() => ({}));
      if (!r.ok) throw new AdapterError(`Hikmah (${r.status}): ${JSON.stringify(b).slice(0, 200)}`, [400, 401, 403, 422].includes(r.status));
      const uuid = b?.data?.uuid || '';
      if (!uuid) throw new AdapterError(`Hikmah: post created without uuid: ${JSON.stringify(b).slice(0, 200)}`, true);
      const slug = b?.data?.slug || '';
      return { destination: 'hikmah', remote_id: uuid, url: slug ? `${base}/posts/${slug}` : '', visibility: 'public', status: 'succeeded', timestamp: new Date().toISOString(), fixture: false };
    },
    async upload(video, title, desc, visibility, creds) {
      const base = (creds?.base_url || '').replace(/\/$/, '');
      if (!base || !creds?.token) throw new AdapterError('Hikmah account disconnected.', true);
      const privacy = visibility === 'public' ? '1' : visibility === 'private' ? '3' : '2';
      const form = new FormData();
      form.append('type', 'video');
      form.append('content', `${title}\n\n${desc}`.slice(0, 20000));
      form.append('privacy', privacy);
      form.append('items[0]', new Blob([fs.readFileSync(video)], { type: 'video/mp4' }), video.split('/').pop() || 'video.mp4');
      const r = await fetch(`${base}/api/posts`, { method: 'POST', headers: { Authorization: `Bearer ${creds.token}`, Accept: 'application/json' }, body: form as any });
      const b: any = await r.json().catch(() => ({}));
      if (!r.ok) throw new AdapterError(`Hikmah (${r.status}): ${JSON.stringify(b).slice(0, 200)}`, [400, 401, 403, 422].includes(r.status));
      const uuid = b?.data?.uuid || '';
      if (!uuid) throw new AdapterError(`Hikmah: post without uuid: ${JSON.stringify(b).slice(0, 200)}`, true);
      const slug = b?.data?.slug || '';
      return { destination: 'hikmah', remote_id: uuid, url: slug ? `${base}/posts/${slug}` : '', visibility, status: 'succeeded', timestamp: new Date().toISOString(), fixture: false };
    },
  },
  fixture: {
    display: 'Fixture (test)', mode: 'fixture',
    setupHelp: 'No setup. Offline tests only.',
    async verify(_c: any) { return { account: 'fixture-test-account' }; },
    async validate(_v: string, _t: string, _d: string, _vis: string) { return []; },
    async upload(video, _t, _d, visibility, _c) { return fixtureReceipt('fixture', video, visibility, 'test double'); },
    async validateText(_t: string) { return []; },
    async postText(text: string, _c: any) {
      return { destination: 'fixture', remote_id: `FIXTURE-TEXT-${text.length}`, url: 'fixture://no-post-performed', visibility: 'public', status: 'succeeded-fixture', timestamp: new Date().toISOString(), fixture: true, note: 'test double' };
    },
  },
};

function fixtureReceipt(destination: string, video: string, visibility: string, note: string): UploadReceipt {
  let h = 'nohash';
  try {
    h = crypto.createHash('sha256').update(fs.readFileSync(video)).digest('hex').slice(0, 10);
  } catch { /* missing file still labeled fixture */ }
  return { destination, remote_id: `FIXTURE-${h}`, url: 'fixture://no-upload-performed', visibility, status: 'succeeded-fixture', timestamp: new Date().toISOString(), fixture: true, note };
}

export function getAdapter(platform: string) {
  const a = adapters[platform];
  if (!a) throw new AdapterError(`Unsupported platform: ${platform} (supported: youtube, facebook, x, hikmah)`, true);
  return a;
}

export function integrationLabel(platform: string): 'real' | 'fixture' | 'unconfigured' | 'blocked' {
  if (platform === 'fixture') return 'fixture';
  if (platform === 'youtube') return process.env.YOUTUBE_PUBLISH_MODE === 'real' ? 'real' : 'unconfigured';
  return 'real'; // facebook/x/hikmah attempt real calls with user-supplied tokens
}
