import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api, clearToken, downloadWithAuth, setToken, token } from './api';
import VideoPreviewPlayer from './VideoPreviewPlayer';

type Page = 'chat' | 'new' | 'jobs' | 'job' | 'accounts' | 'signin';

const READABLE_HINT: Record<string, string> = {
  'research-started': 'Research started',
  'fact-check-completed': 'Fact-check completed',
  'write-ready': 'Draft ready',
  'review-ready': 'Review ready',
  'script-ready': 'Script ready (legacy video)',
  'generating-narration': 'Generating narration (legacy video)',
  'rendering-video': 'Rendering video (legacy video)',
  'video-ready': 'Video ready (legacy video)',
  'upload-completed': 'Upload completed',
  'job-revised': 'Revision requested',
  'job-resumed': 'Job resumed',
};

export default function App() {
  const [page, setPage] = useState<Page>(token() ? 'chat' : 'signin');
  const [authed, setAuthed] = useState(!!token());
  const [jobId, setJobId] = useState('');
  if (!authed) return <SignIn onAuth={() => { setAuthed(true); setPage('chat'); }} />;
  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', maxWidth: 1100, margin: '0 auto', padding: 16 }}>
      <header style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
        <strong>News Documentary Deep Agent</strong>
        {(['chat', 'new', 'jobs', 'accounts'] as Page[]).map((p) => (
          <button key={p} onClick={() => setPage(p)} style={{ fontWeight: page === p ? 700 : 400 }}>
            {p === 'chat' ? 'Main Agent chat' : p === 'new' ? 'New output' : p === 'jobs' ? 'Job history' : 'Connected accounts'}
          </button>
        ))}
        <button onClick={() => { clearToken(); setAuthed(false); setPage('signin'); }}>Sign out</button>
      </header>
      {page === 'chat' && <Chat onJob={(id) => { setJobId(id); setPage('job'); }} />}
      {page === 'new' && <NewDoc onJob={(id) => { setJobId(id); setPage('job'); }} />}
      {page === 'jobs' && <Jobs onOpen={(id) => { setJobId(id); setPage('job'); }} />}
      {page === 'job' && <JobDetail jobId={jobId} />}
      {page === 'accounts' && <Accounts />}
    </div>
  );
}

function SignIn({ onAuth }: { onAuth: () => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const go = async (mode: 'login' | 'register') => {
    setErr('');
    try {
      const out = mode === 'login' ? await api.login(email, password) : await api.register(email, password);
      setToken(out.token);
      onAuth();
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <div style={{ maxWidth: 420, margin: '60px auto', fontFamily: 'system-ui' }}>
      <h2>Sign in</h2>
      <p style={{ color: '#555' }}>Jobs, chats, accounts and publishing are scoped to your account.</p>
      <input placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} style={inp} />
      <input placeholder="password (min 8)" type="password" value={password} onChange={(e) => setPassword(e.target.value)} style={inp} />
      {err && <p style={{ color: 'red' }}>{err}</p>}
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={() => go('login')}>Sign in</button>
        <button onClick={() => go('register')}>Register</button>
      </div>
    </div>
  );
}
const inp: React.CSSProperties = { display: 'block', width: '100%', margin: '8px 0', padding: 8 };

function Chat({ onJob }: { onJob: (id: string) => void }) {
  const [thread, setThread] = useState('chat-1');
  const [msgs, setMsgs] = useState<any[]>([]);
  const [text, setText] = useState('');
  const load = useCallback(async () => {
    try { setMsgs(await api.threadMessages(thread)); } catch { setMsgs([]); }
  }, [thread]);
  useEffect(() => { load(); }, [load]);
  const send = async () => {
    if (!text.trim()) return;
    const out = await api.sendMessage(thread, text);
    setText('');
    await load();
    if (out?.job_id) onJob(out.job_id);
  };
  return (
    <div>
      <h3>Main Agent chat</h3>
      <div>
        <label>Thread <input value={thread} onChange={(e) => setThread(e.target.value)} /></label>
        <button onClick={load}>Reload</button>
      </div>
      <div style={{ border: '1px solid #ddd', padding: 8, minHeight: 200, margin: '8px 0' }}>
        {msgs.map((m: any) => (
          <p key={m.id}><b>{m.role}:</b> {m.content} {m.job_id && <button onClick={() => onJob(m.job_id)}>open {m.job_id}</button>}</p>
        ))}
        {!msgs.length && <p style={{ color: '#888' }}>Ask for a report or posts, e.g. “research a report on …” or “draft social posts about …”.</p>}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && send()} placeholder="Chat with the Main Agent (reports + social posts)…" style={{ flex: 1, padding: 8 }} />
        <button onClick={send}>Send</button>
      </div>
    </div>
  );
}

function NewDoc({ onJob }: { onJob: (id: string) => void }) {
  const [topic, setTopic] = useState('');
  const [jobType, setJobType] = useState<'report' | 'social'>('report');
  const [language, setLanguage] = useState('en');
  const [platforms, setPlatforms] = useState<Record<string, boolean>>({ x: true, facebook: true, hikmah: true });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const create = async () => {
    setBusy(true); setErr('');
    try {
      const j = await api.createJob(topic, {
        topic, job_type: jobType, language,
        platforms: Object.keys(platforms).filter((p) => platforms[p]),
      });
      onJob(j.job_id);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <div>
      <h3>New output</h3>
      <p style={{ color: '#555' }}>Research-based PDF reports and platform-specific social posts. English default; <code>bn</code> for Bengali (PDF needs a Bengali font — see docs). Video generation is disabled in this scope. Closing the browser won't cancel an accepted job.</p>
      <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Topic (required)" style={inp} />
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <label>Output <select value={jobType} onChange={(e) => setJobType(e.target.value as any)}>
          <option value="report">PDF report</option><option value="social">Social posts</option>
        </select></label>
        <label>Language <input value={language} onChange={(e) => setLanguage(e.target.value)} style={{ width: 60 }} /></label>
        {jobType === 'social' && (
          <span>Platforms: {['x', 'facebook', 'hikmah'].map((p) => (
            <label key={p} style={{ marginLeft: 8 }}><input type="checkbox" checked={!!platforms[p]} onChange={(e) => setPlatforms({ ...platforms, [p]: e.target.checked })} /> {p}</label>
          ))} <span style={{ color: '#555' }}>(YouTube copy included for manual use)</span></span>
        )}
      </div>
      {err && <p style={{ color: 'red' }}>{err}</p>}
      <button disabled={busy || !topic.trim()} onClick={create}>{busy ? 'Queueing…' : `Create ${jobType} job`}</button>
    </div>
  );
}

function Jobs({ onOpen }: { onOpen: (id: string) => void }) {
  const [jobs, setJobs] = useState<any[]>([]);
  useEffect(() => { api.jobs().then(setJobs).catch(() => setJobs([])); }, []);
  return (
    <div>
      <h3>Job history</h3>
      {jobs.map((j: any) => (
        <div key={j.job_id} style={{ border: '1px solid #ddd', padding: 8, margin: '6px 0' }}>
          <b>{j.topic}</b> <span style={{ color: '#555' }}>{j.job_id} · {j.job_type || j.settings?.job_type || 'report'} · {j.status}/{j.stage}</span>
          <button style={{ marginLeft: 8 }} onClick={() => onOpen(j.job_id)}>Open</button>
        </div>
      ))}
      {!jobs.length && <p>No jobs yet.</p>}
    </div>
  );
}

function useJobEvents(jobId: string) {
  const [job, setJob] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const afterRef = useRef(0);
  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    let src: EventSource | null = null;
    const t = localStorage.getItem('newsdoc_token') || '';
    // Live SSE; reconnect + persisted replay: refresh replays from after=0.
    try {
      src = new EventSource(`/api/jobs/${jobId}/events?after=0&token=${encodeURIComponent(t)}`);
      src.addEventListener('snapshot', (ev: MessageEvent) => {
        if (alive) setJob(JSON.parse((ev as any).data));
      });
      src.onmessage = (ev: MessageEvent) => {
        try {
          const e = JSON.parse(ev.data);
          if (alive && e?.id) {
            afterRef.current = Math.max(afterRef.current, e.id);
            setEvents((prev) => (prev.some((p: any) => p.id === e.id) ? prev : [...prev, e]));
          }
        } catch { /* keepalive */ }
      };
      src.addEventListener('end', (ev: MessageEvent) => {
        if (alive) setJob(JSON.parse((ev as any).data));
        src?.close();
      });
      src.onerror = () => { src?.close(); src = null; poll(); };
    } catch { poll(); }
    // Polling fallback (same readable events, same auth) + job snapshot.
    let polling = false;
    async function poll() {
      if (polling) return;
      polling = true;
      while (alive && !src) {
        try {
          const j = await api.job(jobId);
          if (alive) setJob(j);
          const evs = await api.jobEvents(jobId, afterRef.current);
          if (alive && evs.length) {
            afterRef.current = Math.max(...evs.map((e: any) => e.id));
            setEvents((prev) => [...prev, ...evs.filter((e: any) => !prev.some((p: any) => p.id === e.id))]);
          }
          const s = (j as any)?.status;
          if (['published', 'failed', 'cancelled', 'done', 'ready_for_user', 'awaiting-approval', 'blocked-no-evidence'].includes(s)) break;
        } catch { /* retry */ }
        await new Promise((r) => setTimeout(r, 2000));
      }
      polling = false;
    }
    const fallback = setTimeout(() => { if (alive && events.length === 0 && !src) poll(); }, 4000);
    return () => { alive = false; clearTimeout(fallback); src?.close(); };
  }, [jobId]);
  return { job, events };
}

function JobDetail({ jobId }: { jobId: string }) {
  const { job, events } = useJobEvents(jobId);
  const [arts, setArts] = useState<any[]>([]);
  const [tab, setTab] = useState<'progress' | 'research' | 'write' | 'publish'>('progress');
  const [doc, setDoc] = useState<any>(null);
  const [revNote, setRevNote] = useState('');
  useEffect(() => {
    if (!jobId) return;
    api.artifacts(jobId).then(setArts).catch(() => setArts([]));
    const t = setInterval(() => api.artifacts(jobId).then(setArts).catch(() => {}), 8000);
    return () => clearInterval(t);
  }, [jobId, job?.status]);
  const fetchText = async (name: string) => {
    const t = localStorage.getItem('newsdoc_token');
    const r = await fetch(`/api/jobs/${jobId}/artifacts/${name}`, { headers: t ? { Authorization: `Bearer ${t}` } : {} });
    if (!r.ok) { setDoc(`Not available yet (${r.status}).`); return; }
    if (name.endsWith('.json')) setDoc(JSON.stringify(await r.json(), null, 2).slice(0, 20000));
    else setDoc((await r.text()).slice(0, 20000));
    setTab(name === 'report.md' || name === 'posts.json' ? 'write' : 'research');
  };
  const requestRevision = async () => {
    if (!revNote.trim()) { setDoc('Type a revision note first (e.g. “shorter summary, focus on prices”).'); return; }
    await api.revise(jobId, revNote);
    setRevNote('');
    setTab('progress');
  };
  if (!jobId) return <p>Open a job from history or chat.</p>;
  const video = arts.find((a: any) => a.name === 'documentary.mp4' || a.name?.endsWith('.mp4'));
  const pdf = arts.find((a: any) => a.name === 'report.pdf');
  const hasSubtitles = arts.some((a: any) => a.name === 'captions.srt');
  const posterArt = arts.find((a: any) => a.name === 'thumbnail.jpg' || a.name === 'thumbnail_jpg');
  const posterName = posterArt ? String(posterArt.name) : 'thumbnail.jpg';
  const jobType = job?.job_type || job?.settings?.job_type || (video ? 'video-legacy' : 'report');
  return (
    <div>
      <h3>Job {jobId}</h3>
      <p>{job?.topic} · {jobType} · <b>{job?.status}</b>/{job?.stage}</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <button onClick={() => api.resume(jobId)}>Resume</button>
        <button onClick={() => api.cancel(jobId)}>Cancel (explicit)</button>
        <button onClick={() => api.jobEvents(jobId).then(() => window.location.reload())}>Refresh (recovers status)</button>
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        {(['progress', 'research', 'write', 'publish'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} style={{ fontWeight: tab === t ? 700 : 400 }}>{t}</button>
        ))}
      </div>
      {tab === 'progress' && (
        <div>
          {events.map((e: any) => (
            <p key={e.id}>[{(READABLE_HINT as any)[e.kind] || e.kind}] {e.message}</p>
          ))}
          {!events.length && <p style={{ color: '#888' }}>Waiting for progress… (reconnecting recovers persisted status)</p>}
        </div>
      )}
      {tab === 'research' && (
        <div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button onClick={() => fetchText('sources.json')}>Sources</button>
            <button onClick={() => fetchText('research_notes.json')}>Research notes</button>
            <button onClick={() => fetchText('fact_report.json')}>Claim verification report</button>
            {arts.some((a: any) => a.name === 'script.json') && <button onClick={() => fetchText('script.json')}>Legacy script (video)</button>}
          </div>
          <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f6f6', padding: 8 }}>{doc || 'Select a document.'}</pre>
        </div>
      )}
      {tab === 'write' && (
        <div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button onClick={() => fetchText('report.md')}>Report (markdown)</button>
            <button onClick={() => fetchText('posts.json')}>Social posts (JSON)</button>
            <button onClick={() => fetchText('review.json')}>Review findings</button>
          </div>
          <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f6f6', padding: 8 }}>{doc || 'Select a document.'}</pre>
          <h4>Request revision</h4>
          <div style={{ display: 'flex', gap: 8 }}>
            <input value={revNote} onChange={(e) => setRevNote(e.target.value)} placeholder="Revision note, e.g. shorter summary, focus on prices" style={{ flex: 1, padding: 8 }} />
            <button onClick={requestRevision}>Revise (reuses research)</button>
          </div>
        </div>
      )}
      {tab === 'publish' && (
        video ? <PublishPanel jobId={jobId} videoReady={!!video} />
        : jobType === 'social' ? <SocialPanel jobId={jobId} />
        : <p>PDF reports publish manually: download the PDF + sources below and share them anywhere. No account needed.</p>
      )}
      {pdf && (
        <div>
          <h4>Preview (exact file offered for download)</h4>
          <PdfPreview
            src={api.streamUrl(jobId, 'report.pdf')}
            name={String(pdf.name)}
            sha256={pdf.sha256}
            sizeBytes={pdf.size_bytes}
          />
        </div>
      )}
      {video && (
        <div>
          <h4>Preview (legacy video — generation disabled in this scope)</h4>
          <VideoPreviewPlayer
            src={api.streamUrl(jobId, String(video.name || 'documentary.mp4'))}
            poster={hasSubtitles ? api.streamUrl(jobId, posterName) : undefined}
            subtitlesSrc={hasSubtitles ? api.vttUrl(jobId) : undefined}
            title="Documentary preview"
            artifact={video}
          />
        </div>
      )}
      {(pdf || video || arts.length > 0) && (
        <div>
          <h4>Downloads (no account needed)</h4>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {arts.filter((a: any) => /\.(pdf|md|mp4|jpg|srt|json|txt)$/.test(a.name)).map((a: any) => (
              <button key={a.name} onClick={() => downloadWithAuth(jobId, a.name, `${jobId}_${a.name}`)}>{a.name}</button>
            ))}
            <button onClick={() => downloadWithAuth(jobId, 'bundle.zip', `${jobId}_bundle.zip`)}>bundle.zip</button>
          </div>
        </div>
      )}
    </div>
  );
}

function PdfPreview({ src, name, sha256, sizeBytes }: { src: string; name: string; sha256?: string; sizeBytes?: number }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const kb = sizeBytes ? `${(sizeBytes / 1024).toFixed(1)} KB` : 'unknown size';
  return (
    <div>
      <p style={{ color: '#555', margin: '4px 0' }}>
        Previewing <code>{name}</code>
        {sha256 && <> · sha256 <code title={sha256}>{sha256.slice(0, 16)}…</code></>}
        {' · '}{kb} · same bytes as download
      </p>
      <div style={{ position: 'relative' }}>
        {loading && !error && <p>Loading PDF preview…</p>}
        {error && <p role="alert" style={{ color: 'red' }}>{error} <button onClick={() => { setError(''); setLoading(true); }}>Retry</button></p>}
        <iframe
          src={src}
          title="PDF report preview"
          style={{ width: '100%', maxWidth: 720, height: 640, border: '1px solid #ddd', background: '#fff' }}
          onLoad={() => setLoading(false)}
          onError={() => { setLoading(false); setError('Could not display the PDF preview. Download it below instead.'); }}
        />
      </div>
    </div>
  );
}

const PLATFORM_LIMITS: Record<string, number> = { x: 280, facebook: 2000, hikmah: 20000, youtube: 5000 };

// Social posts: edit / copy / download, then explicit Review & Publish per
// destination. Connecting an account never publishes. YouTube is disabled for
// connected posting (no text-post API) with the reason shown inline.
function SocialPanel({ jobId }: { jobId: string }) {
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [generated, setGenerated] = useState<Record<string, any>>({});
  const [accs, setAccs] = useState<any[]>([]);
  const [sel, setSel] = useState<Record<string, boolean>>({});
  const [review, setReview] = useState<any>(null);
  const [results, setResults] = useState<any[]>([]);
  const [err, setErr] = useState('');
  const [saved, setSaved] = useState('');
  useEffect(() => {
    api.socialTexts(jobId).then((o) => { setTexts(o.texts || {}); setGenerated(o.generated || {}); }).catch(() => {});
    api.accounts().then(setAccs).catch(() => setAccs([]));
    api.getSocialReview(jobId).then(setReview).catch(() => setReview(null));
  }, [jobId]);
  const save = async () => {
    setErr(''); setSaved('');
    try { await api.saveSocialTexts(jobId, texts); setSaved('Draft saved — not yet authorized.'); }
    catch (e: any) { setErr(e.message); }
  };
  const doReview = async () => {
    setErr('');
    try {
      await api.saveSocialTexts(jobId, texts);
      const selections = accs.filter((a) => sel[a.id]).map((a) => ({ account_id: a.id }));
      setReview(await api.socialReview(jobId, texts, selections));
    } catch (e: any) { setErr(e.message); }
  };
  const doPublish = async () => {
    setErr('');
    try { setResults(await api.socialPublish(jobId)); } catch (e: any) { setErr(e.message); }
  };
  const copy = async (t: string) => {
    try { await navigator.clipboard.writeText(t); setSaved('Copied to clipboard.'); }
    catch { setErr('Copy failed — select the text manually.'); }
  };
  const download = (plat: string, t: string) => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([t], { type: 'text/plain' }));
    a.download = `${jobId}_${plat}.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  };
  return (
    <div>
      <p style={{ color: '#555' }}>Edit, copy or download any text. Publishing needs the two explicit clicks below; changes need a new review.</p>
      {Object.keys(texts).length === 0 && <p style={{ color: '#888' }}>No posts yet — the worker is still writing, or the job failed. Check Progress.</p>}
      {Object.entries(texts).map(([plat, t]) => {
        const lim = PLATFORM_LIMITS[plat] || 20000;
        const g = generated[plat] || {};
        const over = t.length > lim;
        return (
          <div key={plat} style={{ border: '1px solid #ddd', padding: 8, margin: '8px 0' }}>
            <b>{plat}</b> <span style={{ color: over ? 'red' : '#555' }}>{t.length}/{lim} chars</span>
            {g.connect_post === false && <span style={{ color: '#a60' }}> · connected posting disabled: {g.note || 'no text-post API'}</span>}
            {g.claim_ids && <span style={{ color: '#555' }}> · claims: {(g.claim_ids as string[]).join(', ')}</span>}
            <textarea value={t} onChange={(e) => setTexts({ ...texts, [plat]: e.target.value })} rows={4} style={{ width: '100%', marginTop: 4 }} />
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => copy(t)}>Copy</button>
              <button onClick={() => download(plat, t)}>Download .txt</button>
            </div>
          </div>
        );
      })}
      <div style={{ display: 'flex', gap: 8, margin: '8px 0' }}>
        <button onClick={save}>Save edits (draft)</button>
      </div>
      {saved && <p style={{ color: 'green' }}>{saved}</p>}
      <h4>Connected publishing (optional accounts)</h4>
      {accs.filter((a) => a.status === 'connected').map((a: any) => (
        <div key={a.id}>
          <label><input type="checkbox" checked={!!sel[a.id]} onChange={(e) => setSel({ ...sel, [a.id]: e.target.checked })} /> {a.platform} — {a.label} [{a.integration}]</label>
        </div>
      ))}
      {!accs.some((a) => a.status === 'connected') && <p style={{ color: '#888' }}>No connected accounts — connect one on the Connected accounts page, or just copy/download above.</p>}
      {review && <pre style={{ background: '#f6f6f6', padding: 8 }}>{JSON.stringify({ content_hash: String(review.content_hash).slice(0, 16) + '…', destinations: review.selections }, null, 2)}</pre>}
      {err && <p style={{ color: 'red' }}>{err}</p>}
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={doReview}>Review & authorize these texts</button>
        <button onClick={doPublish}>Publish reviewed texts</button>
        <button onClick={async () => setResults(await api.socialRetry(jobId))}>Retry failed only</button>
      </div>
      {results.map((r: any, i: number) => (
        <p key={i}>{r.platform}: <b>{r.status}</b> {r.url || r.remote_id || ''} {r.note || ''} {r.skipped ? '(skipped)' : ''} {r.fixture ? '[fixture]' : ''}</p>
      ))}
    </div>
  );
}

function PublishPanel({ jobId, videoReady }: { jobId: string; videoReady: boolean }) {
  const [accs, setAccs] = useState<any[]>([]);
  const [title, setTitle] = useState('');
  const [desc, setDesc] = useState('');
  const [sel, setSel] = useState<Record<string, boolean>>({});
  const [vis, setVis] = useState<Record<string, string>>({});
  const [review, setReview] = useState<any>(null);
  const [results, setResults] = useState<any[]>([]);
  const [err, setErr] = useState('');
  useEffect(() => {
    api.accounts().then(setAccs).catch(() => setAccs([]));
    api.meta(jobId).then((m) => { setTitle(m.title || ''); setDesc(m.description || ''); }).catch(() => {});
    api.getReview(jobId).then(setReview).catch(() => setReview(null));
  }, [jobId]);
  const doReview = async () => {
    setErr('');
    try {
      await api.saveMeta(jobId, title, desc);
      const selections = accs.filter((a) => sel[a.id]).map((a) => ({ account_id: a.id, platform: a.platform, visibility: vis[a.id] || 'unlisted' }));
      const r = await api.review(jobId, title, desc, selections);
      setReview(r);
    } catch (e: any) { setErr(e.message); }
  };
  const doPublish = async () => {
    setErr('');
    try { setResults(await api.publish(jobId)); } catch (e: any) { setErr(e.message); }
  };
  if (!videoReady) return <p>No finished video yet.</p>;
  return (
    <div>
      <p style={{ color: '#555' }}>Connecting an account never publishes. Two explicit clicks required: <b>Review & authorize</b> then <b>Publish</b>. Changes need a new review.</p>
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" style={inp} />
      <textarea value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Description" rows={4} style={{ width: '100%' }} />
      {accs.filter((a) => a.status === 'connected').map((a: any) => (
        <div key={a.id}>
          <label><input type="checkbox" checked={!!sel[a.id]} onChange={(e) => setSel({ ...sel, [a.id]: e.target.checked })} /> {a.platform} — {a.label} [{a.integration}]</label>
          <select value={vis[a.id] || 'unlisted'} onChange={(e) => setVis({ ...vis, [a.id]: e.target.value })}>
            <option value="public">public</option><option value="unlisted">unlisted</option><option value="private">private</option>
          </select>
        </div>
      ))}
      {review && <pre style={{ background: '#f6f6f6', padding: 8 }}>{JSON.stringify({ video_hash: String(review.video_hash).slice(0, 16) + '…', title: review.title, destinations: review.selections }, null, 2)}</pre>}
      {err && <p style={{ color: 'red' }}>{err}</p>}
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={doReview}>Review & authorize this version</button>
        <button onClick={doPublish}>Publish reviewed version</button>
        <button onClick={async () => setResults(await api.retry(jobId))}>Retry failed only</button>
      </div>
      {results.map((r: any, i: number) => (
        <p key={i}>{r.platform}: <b>{r.status}</b> {r.url || r.remote_id || ''} {r.note || ''} {r.skipped ? '(skipped)' : ''} {r.fixture ? '[fixture]' : ''}</p>
      ))}
    </div>
  );
}

function Accounts() {
  const [accs, setAccs] = useState<any[]>([]);
  const [platform, setPlatform] = useState('youtube');
  const [label, setLabel] = useState('my-account');
  const [secretText, setSecretText] = useState('{}');
  const [err, setErr] = useState('');
  const load = () => api.accounts().then(setAccs).catch(() => setAccs([]));
  useEffect(() => { load(); }, []);
  const connect = async () => {
    setErr('');
    try {
      let secret: any = {};
      try { secret = JSON.parse(secretText); } catch { throw new Error('Secret must be JSON. YouTube: {"token_file": "/path/token.json"}; Facebook: {"page_id": "...", "page_token": "..."}; X: {"access_token": "..."}; Hikmah: {"base_url": "https://hikmah.net", "token": "..."}'); }
      await api.connectAccount(platform, label, secret);
      setSecretText('{}');
      load();
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <div>
      <h3>Connected accounts</h3>
      <p style={{ color: '#555' }}>Tokens stay server-side encrypted, never reach the LLM or browser storage. Connecting never publishes.</p>
      {accs.map((a: any) => (
        <div key={a.id} style={{ border: '1px solid #ddd', padding: 8, margin: '6px 0' }}>
          {a.platform} — {a.label} [{a.status}/{a.integration}]
          <button style={{ marginLeft: 8 }} onClick={() => api.disconnectAccount(a.id).then(load)}>Disconnect</button>
        </div>
      ))}
      <h4>Connect a new account</h4>
      <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
        <option value="youtube">youtube</option><option value="facebook">facebook</option>
        <option value="x">x</option><option value="hikmah">hikmah</option><option value="fixture">fixture (test)</option>
      </select>
      <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="label" />
      <textarea value={secretText} onChange={(e) => setSecretText(e.target.value)} rows={4} style={{ width: '100%' }} />
      {err && <p style={{ color: 'red' }}>{err}</p>}
      <button onClick={connect}>Verify & connect (stores nothing on failure)</button>
    </div>
  );
}
