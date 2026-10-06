// Shared API client (same backend the CLI uses).
const API = (import.meta as any).env?.VITE_API_URL || '';

export function token(): string | null { return localStorage.getItem('newsdoc_token'); }
export function setToken(t: string) { localStorage.setItem('newsdoc_token', t); }
export function clearToken() { localStorage.removeItem('newsdoc_token'); }

async function req(method: string, path: string, body?: any): Promise<any> {
  const t = token();
  const r = await fetch(`${API}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) { clearToken(); throw new Error('Signed out — please sign in again.'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((j as any)?.error || `Request failed (${r.status})`);
  return j;
}

export const api = {
  register: (email: string, password: string) => req('POST', '/api/auth/register', { email, password }),
  login: (email: string, password: string) => req('POST', '/api/auth/login', { email, password }),
  threads: () => req('GET', '/api/chat/threads'),
  threadMessages: (id: string) => req('GET', `/api/chat/threads/${id}`),
  sendMessage: (id: string, content: string, settings?: any) => req('POST', `/api/chat/threads/${id}/messages`, { content, settings }),
  createJob: (topic: string, settings: any, thread_id?: string) => req('POST', '/api/jobs', { topic, settings, thread_id }),
  jobs: () => req('GET', '/api/jobs'),
  job: (id: string) => req('GET', `/api/jobs/${id}`),
  jobEvents: (id: string, after = 0) => req('GET', `/api/jobs/${id}/job-events?after=${after}`),
  resume: (id: string) => req('POST', `/api/jobs/${id}/resume`, {}),
  cancel: (id: string) => req('POST', `/api/jobs/${id}/cancel`, {}),
  revise: (id: string, note: string) => req('POST', `/api/jobs/${id}/revise`, { note }),
  socialTexts: (id: string) => req('GET', `/api/social/${id}/texts`),
  saveSocialTexts: (id: string, texts: Record<string, string>) => req('PUT', `/api/social/${id}/texts`, { texts }),
  socialReview: (id: string, texts: Record<string, string>, selections: any[]) => req('POST', `/api/social/${id}/review`, { texts, selections }),
  getSocialReview: (id: string) => req('GET', `/api/social/${id}/review`),
  socialPublish: (id: string) => req('POST', `/api/social/${id}/publish`, {}),
  socialRetry: (id: string) => req('POST', `/api/social/${id}/retry`, {}),
  socialPublications: (id: string) => req('GET', `/api/social/${id}/publications`),
  artifacts: (id: string) => req('GET', `/api/jobs/${id}/artifacts`),
  /** Direct authorized URLs for <video>/<track>/poster: HTTP byte-range
   *  streaming, no full download. Same JWT as the query fallback the API
   *  verifies identically to the Authorization header. */
  streamUrl: (id: string, name: string) =>
    `${API}/api/jobs/${id}/artifacts/${encodeURIComponent(name)}?token=${encodeURIComponent(token() || '')}`,
  /** Generated WebVTT for browser playback (SRT stays the download format). */
  vttUrl: (id: string) =>
    `${API}/api/jobs/${id}/captions.vtt?token=${encodeURIComponent(token() || '')}`,
  // Note: artifact downloads use Authorization header via fetch; direct <a> links below use same-origin proxy + token param handled by хук.
  accounts: () => req('GET', '/api/accounts'),
  connectAccount: (platform: string, label: string, secret: any) => req('POST', '/api/accounts/connect', { platform, label, secret }),
  disconnectAccount: (id: string) => req('DELETE', `/api/accounts/${id}`),
  meta: (id: string) => req('GET', `/api/publish/${id}/meta`),
  saveMeta: (id: string, title: string, description: string) => req('PUT', `/api/publish/${id}/meta`, { title, description }),
  review: (id: string, title: string, description: string, selections: any[]) => req('POST', `/api/publish/${id}/review`, { title, description, selections }),
  getReview: (id: string) => req('GET', `/api/publish/${id}/review`),
  publish: (id: string) => req('POST', `/api/publish/${id}/publish`, {}),
  retry: (id: string) => req('POST', `/api/publish/${id}/retry`, {}),
  publications: (id: string) => req('GET', `/api/publish/${id}/publications`),
  prefs: () => req('GET', '/api/me/preferences'),
  savePrefs: (p: any) => req('PUT', '/api/me/preferences', p),
};

export async function downloadWithAuth(jobId: string, name: string, filename: string) {
  const t = token();
  const r = await fetch(`${API}/api/jobs/${jobId}/artifacts/${encodeURIComponent(name)}`, {
    headers: t ? { Authorization: `Bearer ${t}` } : {},
  });
  if (!r.ok) throw new Error(`Download failed (${r.status})`);
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
