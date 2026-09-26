import { Suspense, lazy, useEffect, useRef, useState } from 'react';

const DocumentViewer = lazy(() => import('../components/DocumentViewer'));
import { Link } from 'react-router';
import {
  type DocumentDetail,
  type DocumentStatus,
  type DocumentSummary,
  type ToolInvocationDto,
  getDocument,
  listDocuments,
  listToolInvocations,
  uploadDocument,
} from '../api';
import { CheckIcon, UploadIcon } from '../components/Icons';
import { CopyButton } from '../components/CopyButton';
import { StatusPill } from '../components/StatusPill';
import { type PipelineStep, pipelineSteps } from '../lib/documents';
import { selectableRow } from '../lib/rowSelect';
import { formatUtc, formatUtcFull } from '../lib/time';
import './Documents.css';

const POLL_MS = 3000;
const USED_BY_LIMIT = 5;

type Filter = 'all' | DocumentStatus;

const FILTERS: Array<{ id: Filter; label: string }> = [
  { id: 'all', label: 'All documents' },
  { id: 'ready', label: 'Indexed' },
  { id: 'processing', label: 'Processing' },
  { id: 'failed', label: 'Failed' },
];

function formatBytes(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function shortSha(sha: string): string {
  return `${sha.slice(0, 6)}…${sha.slice(-4)}`;
}

interface StatusCellProps {
  doc: DocumentSummary;
}

function StatusCell({ doc }: StatusCellProps) {
  if (doc.status === 'ready') return <StatusPill variant="success">Indexed</StatusPill>;
  if (doc.status === 'processing') return <StatusPill variant="accent">Processing…</StatusPill>;
  return (
    <>
      <StatusPill variant="warning">Failed</StatusPill> <span className="mono documents__status-note">{doc.status_note}</span>
    </>
  );
}

interface PipelineProps {
  steps: PipelineStep[];
}

function Pipeline({ steps }: PipelineProps) {
  return (
    <ol className="documents__stepper">
      {steps.map((step) => (
        <li key={step.stage}>
          <span className={`documents__step-dot documents__step-dot--${step.state}`}>
            {step.state === 'done' && <CheckIcon size={10} />}
          </span>
          <span className="documents__step-label">{step.label}</span>
          <span className="mono documents__step-time">
            {step.state === 'active' ? 'running' : step.state === 'failed' ? 'failed' : step.duration ?? ''}
          </span>
        </li>
      ))}
    </ol>
  );
}

interface UsedByProps {
  invocations: ToolInvocationDto[];
}

function UsedBy({ invocations }: UsedByProps) {
  if (invocations.length === 0) return <p className="documents__empty">Not used by any tool invocation yet.</p>;
  return (
    <>
      {invocations.slice(0, USED_BY_LIMIT).map((invocation) => (
        <div key={invocation.id} className="documents__used-by">
          <div>
            <div className="mono documents__used-tool">{invocation.tool_name}</div>
            <div className="mono documents__id">{formatUtc(invocation.created_at)}</div>
          </div>
          {invocation.decision?.posting_id ? (
            <Link to={`/ledger?posting=${invocation.decision.posting_id}`}>View posting →</Link>
          ) : invocation.approval_required && invocation.decision === null ? (
            <Link to="/review#approvals">Awaiting approval →</Link>
          ) : (
            <span className="documents__empty">{invocation.decision ? 'Rejected' : 'Lookup'}</span>
          )}
        </div>
      ))}
    </>
  );
}

export function Documents() {
  const [filter, setFilter] = useState<Filter>('all');
  const [summaries, setSummaries] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | undefined>();
  const [invocations, setInvocations] = useState<ToolInvocationDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [viewingPage, setViewingPage] = useState<number | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      listDocuments()
        .then((rows) => {
          if (cancelled) return;
          setSummaries(rows);
          setError(null);
        })
        .catch((e: Error) => !cancelled && setError(e.message));
    void load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    listToolInvocations({ limit: 200 })
      .then(setInvocations)
      .catch(() => setInvocations([]));
  }, []);

  const currentId = selectedId ?? summaries[0]?.id ?? null;
  const current = summaries.find((s) => s.id === currentId);
  // refetch the detail only when the selection or its ingestion progress changes, not on every poll
  const progressKey = current ? `${current.status}:${current.element_count}` : null;

  useEffect(() => {
    if (!currentId) return;
    getDocument(currentId)
      .then(setDetail)
      .catch((e: Error) => setError(e.message));
  }, [currentId, progressKey]);

  const rows = filter === 'all' ? summaries : summaries.filter((d) => d.status === filter);
  const count = (id: Filter) => (id === 'all' ? summaries.length : summaries.filter((d) => d.status === id).length);
  const indexedChunks = summaries.reduce((sum, d) => sum + (d.status === 'ready' ? d.element_count : 0), 0);
  const preview = detail && detail.id === currentId ? detail.preview : [];
  const usedBy = current ? invocations.filter((inv) => inv.input.document_id === current.id) : [];

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
              Every uploaded contract and its ingestion pipeline — parse, tokenise, index, extract. Answers in Chat cite
              these chunks by page and section.
            </p>
            <p className="documents__stack mono">
              Parser: Docling (local) · PII: Presidio tokens · Search: Postgres full-text + Pinecone · Embeddings:
              text-embedding-3-small
            </p>
          </div>
          <div className="documents__upload">
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf"
              hidden
              onChange={(e) => void onUpload(e.target.files?.[0])}
            />
            <button type="button" className="btn btn-primary" onClick={() => fileInput.current?.click()}>
              <UploadIcon size={14} /> Upload document
            </button>
            <span className="mono">PDF with a text layer · scanned files are rejected</span>
            {error && (
              <span className="mono documents__status-note--error" role="alert">
                {error}
              </span>
            )}
          </div>
        </div>

        <div className="documents__filters">
          {FILTERS.map((f) => (
            <button
              type="button"
              key={f.id}
              aria-pressed={filter === f.id}
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
                      className={doc.id === currentId ? 'documents__row--selected' : undefined}
                      {...selectableRow(doc.id === currentId, () => setSelectedId(doc.id))}
                    >
                      <td>
                        <div className="documents__name" title={doc.title}>
                          {doc.title}
                        </div>
                        <div className="documents__id mono">{doc.id}</div>
                      </td>
                      <td className="num">{doc.page_count}</td>
                      <td className="num">{doc.element_count || '—'}</td>
                      <td className="mono documents__uploaded">{formatUtc(doc.uploaded_at)}</td>
                      <td>
                        <StatusCell doc={doc} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="documents__table-foot mono">
              <span>
                {summaries.length} documents · {indexedChunks} chunks indexed
              </span>
              <span>All timestamps UTC</span>
            </div>
          </div>

          {current ? (
            <aside className="panel documents__detail">
              <div className="documents__detail-head">
                <span className="documents__label mono">Document</span>
                <StatusCell doc={current} />
              </div>
              <h2 className="documents__detail-name">{current.title}</h2>
              <div className="documents__detail-id mono">
                {current.id} <CopyButton value={current.id} />
              </div>

              <dl className="documents__meta">
                <dt>Pages</dt>
                <dd className="mono">
                  {current.page_count}
                  {current.status === 'ready' && (
                    <button type="button" className="btn documents__view-btn" onClick={() => setViewingPage(1)}>
                      View
                    </button>
                  )}
                </dd>
                <dt>Chunks</dt>
                <dd className="mono">{current.element_count || '—'}</dd>
                <dt>Uploaded</dt>
                <dd className="mono">{formatUtcFull(current.uploaded_at)}</dd>
                <dt>Size</dt>
                <dd className="mono">{formatBytes(current.byte_size)}</dd>
                <dt>SHA-256</dt>
                <dd className="mono">
                  {shortSha(current.file_sha256)} <CopyButton value={current.file_sha256} />
                </dd>
              </dl>

              <section className="documents__section">
                <div className="documents__section-head">Pipeline</div>
                <Pipeline steps={pipelineSteps(current.events, current.status)} />
                {current.status === 'failed' && current.status_note && (
                  <p className="documents__empty">{current.status_note}</p>
                )}
              </section>

              <section className="documents__section">
                <div className="documents__section-head">
                  Chunks
                  <span className="mono documents__filter-count">{current.element_count}</span>
                </div>
                {preview.length === 0 ? (
                  <p className="documents__empty">No chunks indexed yet.</p>
                ) : (
                  <>
                    <ul className="documents__chunks">
                      {preview.map((c) => (
                        <li key={c.ordinal} className="documents__chunk">
                          <div className="mono documents__chunk-loc">
                            p.{c.page_start} · {c.section_path.join(' › ') || c.kind}
                          </div>
                          <div className="documents__chunk-text">{c.text}</div>
                        </li>
                      ))}
                    </ul>
                    <p className="documents__empty">
                      Showing the first {preview.length} of {current.element_count} chunks.
                    </p>
                  </>
                )}
              </section>

              <section className="documents__section">
                <div className="documents__section-head">Used by</div>
                <UsedBy invocations={usedBy} />
              </section>
            </aside>
          ) : (
            <aside className="panel documents__detail">
              <p className="documents__empty">Upload a contract to get started.</p>
            </aside>
          )}
        </div>
      </div>
      {viewingPage !== null && current && (
        <Suspense fallback={<div className="viewer-overlay"><div className="viewer documents__empty">Loading viewer...</div></div>}>
          <DocumentViewer
            documentId={current.id}
            version={current.version}
            pageCount={current.page_count}
            onClose={() => setViewingPage(null)}
          />
        </Suspense>
      )}
    </div>
  );
}
