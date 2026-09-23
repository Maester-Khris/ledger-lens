import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { type DocumentDetail, type DocumentSummary, getDocument, listDocuments, uploadDocument } from '../api';
import { CheckIcon, UploadIcon } from '../components/Icons';
import { CopyButton } from '../components/CopyButton';
import { StatusPill } from '../components/StatusPill';
import './Documents.css';

type DocStatus = 'processing' | 'indexed' | 'failed';

type Doc = {
  id: string;
  name: string;
  pages: number | null;
  chunks: number | null;
  uploadedAt: string;
  uploadedAtFull: string;
  status: DocStatus;
  statusNote?: string;
  size: string;
  sha256: string;
  pipeline: Array<{ step: string; duration: string }>;
  chunkPreview: Array<{ location: string; text: string }>;
  usedBy: Array<{ tool: string; toolInvocation: string; posting: string }>;
};

const STAGE_LABELS: Record<string, string> = {
  stored: 'Stored (content-addressed)',
  parsed: 'Parsed + PII tokenised (Docling, Presidio)',
  indexed: 'Indexed (Postgres full-text + Pinecone)',
  extracted: 'Fee terms extracted',
  failed: 'Stage failed',
};
const POLL_MS = 3000;

function formatBytes(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function toDoc(summary: DocumentSummary, detail?: DocumentDetail): Doc {
  const at = new Date(summary.uploaded_at);
  const events = summary.events;
  return {
    id: summary.id,
    name: summary.title,
    pages: summary.page_count,
    chunks: summary.element_count || null,
    uploadedAt: at.toUTCString().slice(5, 22) + ' UTC',
    uploadedAtFull: at.toUTCString(),
    status: summary.status === 'ready' ? 'indexed' : summary.status,
    statusNote: summary.status_note ?? undefined,
    size: formatBytes(summary.byte_size),
    sha256: `${summary.file_sha256.slice(0, 6)}…${summary.file_sha256.slice(-4)}`,
    pipeline: events.map((e, i) => ({
      step: STAGE_LABELS[e.stage] ?? e.stage,
      duration: i === 0 ? '—' : `${((Date.parse(e.at) - Date.parse(events[i - 1].at)) / 1000).toFixed(1)}s`,
    })),
    chunkPreview: (detail?.preview ?? []).map((p) => ({
      location: `p.${p.page_start} · ${p.section_path.join(' › ') || p.kind}`,
      text: p.text,
    })),
    usedBy: [],
  };
}

function statusCell(doc: Doc) {
  if (doc.status === 'indexed') return <StatusPill variant="success">Indexed</StatusPill>;
  if (doc.status === 'processing') return <StatusPill variant="accent">Processing…</StatusPill>;
  return (
    <>
      <StatusPill variant="warning">Failed</StatusPill>{' '}
      <span className="mono documents__status-note">
        {doc.statusNote}
      </span>
    </>
  );
}

const FILTERS: Array<{ id: 'all' | DocStatus; label: string }> = [
  { id: 'all', label: 'All documents' },
  { id: 'indexed', label: 'Indexed' },
  { id: 'processing', label: 'Processing' },
  { id: 'failed', label: 'Failed' },
];

export function Documents() {
  const [filter, setFilter] = useState<'all' | DocStatus>('all');
  const [summaries, setSummaries] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | undefined>();
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      listDocuments()
        .then((rows) => !cancelled && setSummaries(rows))
        .catch((e: Error) => !cancelled && setError(e.message));
    void load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const currentId = selectedId ?? summaries[0]?.id ?? null;
  useEffect(() => {
    if (currentId) getDocument(currentId).then(setDetail).catch((e: Error) => setError(e.message));
  }, [currentId, summaries]);

  const DOCS = summaries.map((s) => toDoc(s, s.id === detail?.id ? detail : undefined));
  const rows = filter === 'all' ? DOCS : DOCS.filter((d) => d.status === filter);
  const count = (id: 'all' | DocStatus) => (id === 'all' ? DOCS.length : DOCS.filter((d) => d.status === id).length);
  const indexedChunks = DOCS.reduce((sum, d) => sum + (d.status === 'indexed' ? d.chunks ?? 0 : 0), 0);
  const selected = DOCS.find((d) => d.id === currentId);

  const onUpload = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    try {
      const { document_id } = await uploadDocument(file);
      setSelectedId(document_id);
      setSummaries(await listDocuments());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    }
  };

  return (
    <div className="documents">
      <div className="documents__topbar">
        <span className="documents__breadcrumb">
          <span>Documents</span>
        </span>
      </div>

      <div className="documents__body">
        <div className="documents__header">
          <div>
            <h1 className="documents__title">Documents</h1>
            <p className="documents__subtitle">
              Every uploaded document and its ingestion pipeline — parse, chunk, embed, index.
              Answers in Chat cite these chunks by page and section.
            </p>
            <p className="documents__stack mono">
              Parser: Docling (local) · PII: Presidio tokens · Search: Postgres full-text + Pinecone · Embeddings: text-embedding-3-small
            </p>
          </div>
          <div className="documents__upload">
            <input ref={fileInput} type="file" accept="application/pdf" hidden onChange={(e) => void onUpload(e.target.files?.[0])} />
            <button type="button" className="btn btn-primary" onClick={() => fileInput.current?.click()}>
              <UploadIcon size={14} /> Upload document
            </button>
            <span className="mono">PDF with a text layer · scanned files are rejected</span>
            {error && <span className="mono documents__status-note--error">{error}</span>}
          </div>
        </div>

        <div className="documents__filters">
          {FILTERS.map((f) => (
            <button
              type="button"
              key={f.id}
              className={`documents__filter-chip${filter === f.id ? ' documents__filter-chip--active' : ''}`}
              onClick={() => setFilter(f.id)}
            >
              {f.label} <span className="mono documents__filter-count">{count(f.id)}</span>
            </button>
          ))}
        </div>

        <div className="documents__grid">
          <div className="panel documents__table-panel">
            <div className="scroll-x">
              <table className="data-table">
                <colgroup>
                  <col />
                  <col className="col-num" />
                  <col className="col-num" />
                  <col className="col-uploaded" />
                  <col className="col-status" />
                </colgroup>
                <thead>
                  <tr>
                    <th>Document</th>
                    <th style={{ textAlign: 'right' }}>Pages</th>
                    <th style={{ textAlign: 'right' }}>Chunks</th>
                    <th>Uploaded</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((doc) => (
                    <tr
                      key={doc.id}
                      className={doc.id === selectedId ? 'documents__row--selected' : undefined}
                      onClick={() => setSelectedId(doc.id)}
                    >
                      <td>
                        <div className="documents__name" title={doc.name}>
                          {doc.name}
                        </div>
                        <div className="documents__id mono">{doc.id}</div>
                      </td>
                      <td className="num">{doc.pages ?? '—'}</td>
                      <td className="num">{doc.chunks ?? '—'}</td>
                      <td className="mono documents__uploaded">{doc.uploadedAt}</td>
                      <td>{statusCell(doc)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="documents__table-foot mono">
              <span>
                {DOCS.length} documents · {indexedChunks} chunks indexed
              </span>
              <span>All timestamps UTC</span>
            </div>
          </div>

          {selected ? (<aside className="panel documents__detail">
            <div className="documents__detail-head">
              <span className="documents__label mono">Document</span>
              {statusCell(selected)}
            </div>
            <h2 className="documents__detail-name">{selected.name}</h2>
            <div className="documents__detail-id mono">
              {selected.id} <CopyButton value={selected.id} />
            </div>

            <dl className="documents__meta">
              <dt>Pages</dt>
              <dd className="mono">{selected.pages ?? '—'}</dd>
              <dt>Chunks</dt>
              <dd className="mono">{selected.chunks ?? '—'}</dd>
              <dt>Uploaded</dt>
              <dd className="mono">{selected.uploadedAtFull}</dd>
              <dt>Size</dt>
              <dd className="mono">{selected.size}</dd>
              <dt>SHA-256</dt>
              <dd className="mono">
                {selected.sha256} <CopyButton value={selected.sha256} />
              </dd>
            </dl>

            <section className="documents__section">
              <div className="documents__section-head">Pipeline</div>
              {selected.pipeline.length === 0 ? (
                <p className="documents__empty">{selected.statusNote}</p>
              ) : (
                <ol className="documents__stepper">
                  {selected.pipeline.map((p) => (
                    <li key={p.step}>
                      <span
                        className={`documents__step-dot${p.duration === '…' ? ' documents__step-dot--active' : ''}`}
                      >
                        {p.duration !== '…' && <CheckIcon size={10} />}
                      </span>
                      <span className="documents__step-label">{p.step}</span>
                      <span className="mono documents__step-time">{p.duration}</span>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section className="documents__section">
              <div className="documents__section-head">
                Chunks
                <span className="mono documents__filter-count">{selected.chunks ?? 0}</span>
              </div>
              {selected.chunkPreview.length === 0 ? (
                <p className="documents__empty">No chunks indexed yet.</p>
              ) : (
                <>
                  <ul className="documents__chunks">
                    {selected.chunkPreview.map((c) => (
                      <li key={c.location} className="documents__chunk">
                        <div className="mono documents__chunk-loc">{c.location}</div>
                        <div className="documents__chunk-text">{c.text}</div>
                      </li>
                    ))}
                  </ul>
                  <a href="#chunks" className="documents__more">
                    Show all {selected.chunks} chunks →
                  </a>
                </>
              )}
            </section>

            <section className="documents__section">
              <div className="documents__section-head">Used by</div>
              {selected.usedBy.length === 0 ? (
                <p className="documents__empty">Not used by any tool invocation yet.</p>
              ) : (
                selected.usedBy.map((u) => (
                  <div key={u.toolInvocation} className="documents__used-by">
                    <div>
                      <div className="mono documents__used-tool">{u.tool}</div>
                      <div className="mono documents__id">
                        {u.toolInvocation} → posting {u.posting}
                      </div>
                    </div>
                    <Link to="/ledger">View posting →</Link>
                  </div>
                ))
              )}
            </section>
          </aside>) : <aside className="panel documents__detail"><p className="documents__empty">Upload a contract to get started.</p></aside>}
        </div>
      </div>
    </div>
  );
}
