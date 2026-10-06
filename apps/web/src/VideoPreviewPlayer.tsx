import { useRef, useState } from 'react';

export interface PreviewArtifact {
  name: string;
  sha256?: string;
  size_bytes?: number;
}

interface Props {
  /** Authorized streaming URL (HTTP byte-range capable). Must point at the
   *  exact artifact bytes the user will download or approve. */
  src: string;
  /** Thumbnail poster URL (authorized). Shown before playback starts. */
  poster?: string;
  /** WebVTT subtitles URL (authorized). SRT stays the downloadable format. */
  subtitlesSrc?: string;
  title?: string;
  /** Artifact record for the version badge (hash + size). */
  artifact?: PreviewArtifact | null;
}

function mediaErrorMessage(code: number | undefined): string {
  switch (code) {
    case 1: return 'Playback aborted. Please press play to retry.';
    case 2: return 'Network error while loading the video. Check your connection and retry — your place is kept via streaming.';
    case 3: return 'This browser could not decode the video. Try downloading the MP4 and playing it locally.';
    case 4: return 'Video source not supported or not found. The job may still be rendering — refresh to recover status.';
    default: return 'Could not play this preview. Refresh to recover the persisted job status, or download the MP4 below.';
  }
}

export function formatBytes(n?: number): string {
  if (!n && n !== 0) return 'unknown size';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Reusable documentary preview: native HTML5 video with controls (play,
 * seek, volume, fullscreen), thumbnail poster and English WebVTT subtitles.
 * Streams over HTTP byte-ranges so seeking never downloads the whole file.
 * Always shows which exact artifact version is previewed. */
export default function VideoPreviewPlayer({ src, poster, subtitlesSrc, title, artifact }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);

  const hash = (artifact?.sha256 || '').slice(0, 16);

  return (
    <div>
      {(title || artifact) && (
        <p style={{ color: '#555', margin: '4px 0' }}>
          {title && <b>{title} </b>}
          {artifact && (
            <span title={artifact.sha256 || ''}>
              · previewing <code>{artifact.name}</code>
              {hash && <> · sha256 <code>{hash}…</code></>}
              {' · '}{formatBytes(artifact.size_bytes)}
              {' · '}same bytes as download &amp; approval
            </span>
          )}
        </p>
      )}
      <div style={{ position: 'relative', background: '#000', maxWidth: 480 }}>
        <video
          key={attempt}
          ref={videoRef}
          controls
          preload="metadata"
          poster={poster}
          playsInline
          style={{ width: '100%', display: 'block', aspectRatio: '9/16', background: '#000' }}
          onCanPlay={() => { setLoading(false); setError(''); }}
          onWaiting={() => setLoading(true)}
          onPlaying={() => { setLoading(false); setError(''); }}
          onError={(e) => {
            const code = (e.currentTarget.error as MediaError | null)?.code;
            setLoading(false);
            setError(mediaErrorMessage(code));
          }}
        >
          <source src={src} type="video/mp4" />
          {subtitlesSrc && (
            <track kind="subtitles" src={subtitlesSrc} srcLang="en" label="English" default />
          )}
        </video>
        {loading && !error && (
          <div style={overlay}>
            <p>Loading preview…</p>
            <p style={{ fontSize: 12 }}>Streaming — seeking works before the full file arrives.</p>
          </div>
        )}
        {error && (
          <div style={overlay} role="alert">
            <p><b>Preview error.</b></p>
            <p>{error}</p>
            <button onClick={() => { setError(''); setLoading(true); setAttempt((a) => a + 1); }}>Retry preview</button>
          </div>
        )}
      </div>
      <p style={{ color: '#555', fontSize: 12 }}>
        Native playback: play/pause, seek bar, volume, fullscreen. English subtitles via WebVTT
        {subtitlesSrc ? '' : ' (not ready yet)'} · poster: job thumbnail.
      </p>
    </div>
  );
}

const overlay: React.CSSProperties = {
  position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
  alignItems: 'center', justifyContent: 'center', color: '#fff',
  background: 'rgba(0,0,0,0.55)', textAlign: 'center', padding: 12,
};
