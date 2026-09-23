import { useState } from 'react';
import { Link } from 'react-router';
import { CheckIcon, UploadIcon } from '../components/Icons';
import { CopyButton } from '../components/CopyButton';
import { StatusPill } from '../components/StatusPill';
import './Documents.css';

type DocStatus = 'processing' | 'indexed' | 'failed';

type Chunk = {
  location: string;
  text: string;
};

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
  pipeline: { step: string; duration: string }[];
  chunkPreview: Chunk[];
  usedBy: { tool: string; toolInvocation: string; posting: string }[];
};

const DOCS: Doc[] = [
  {
    id: 'doc_7f3a21c9',
    name: '2024_T4_AcmeCorp.pdf',
    pages: 2,
    chunks: 14,
    uploadedAt: 'Sep 22, 09:14 UTC',
    uploadedAtFull: 'Sep 22, 2026 09:14:03 UTC',
    status: 'indexed',
    size: '184 KB',
    sha256: '4f89d1…3c9a',
    pipeline: [
      { step: 'Parsed (LlamaParse)', duration: '6.2s' },
      { step: 'Chunked by structure', duration: '0.1s' },
      { step: 'Embedded', duration: '1.4s' },
      { step: 'Indexed in Pinecone', duration: '0.3s' },
    ],
    chunkPreview: [
      {
        location: 'p.1 · Employer information',
        text: 'Acme Corp Technologies Inc. · Business number 12345 6789 RP0001…',
      },
      {
        location: 'p.1 · Employment income',
        text: 'Box 14 Employment income 94,500.00 · Box 22 Income tax deducted 18,212.40…',
      },
      {
        location: 'p.1 · Deductions',
        text: 'Box 16 CPP contributions 3,867.50 · Box 18 EI premiums 1,049.12…',
      },
      {
        location: 'p.2 · Other information',
        text: 'Box 40 Other taxable allowances 0.00…',
      },
    ],
    usedBy: [{ tool: 'total_reported_income', toolInvocation: 'ti_0192e4b1', posting: 'pst_98f102a4' }],
  },
  {
    id: 'doc_3b8e0f12',
    name: '2024_W2_AcmeCorp.pdf',
    pages: 1,
    chunks: 9,
    uploadedAt: 'Sep 22, 09:16 UTC',
    uploadedAtFull: 'Sep 22, 2026 09:16:27 UTC',
    status: 'indexed',
    size: '96 KB',
    sha256: '9b21ce…07d4',
    pipeline: [
      { step: 'Parsed (LlamaParse)', duration: '3.8s' },
      { step: 'Chunked by structure', duration: '0.1s' },
      { step: 'Embedded', duration: '0.9s' },
      { step: 'Indexed in Pinecone', duration: '0.2s' },
    ],
    chunkPreview: [
      {
        location: 'p.1 · Wages, tips, other compensation',
        text: 'Box 1 Wages, tips, other compensation 61,300.00 · Box 2 Federal income tax withheld 9,874.00…',
      },
      {
        location: 'p.1 · Employer',
        text: 'Employer identification number 12-3456789 · Acme Corp Technologies Inc.…',
      },
    ],
    usedBy: [{ tool: 'total_reported_income', toolInvocation: 'ti_0187c2d6', posting: 'pst_31b74281' }],
  },
  {
    id: 'doc_a41c77d0',
    name: '2024_T5_Investment_Scanned.pdf',
    pages: 3,
    chunks: 22,
    uploadedAt: 'Sep 22, 09:21 UTC',
    uploadedAtFull: 'Sep 22, 2026 09:21:40 UTC',
    status: 'indexed',
    size: '2.1 MB',
    sha256: 'c07e5a…91bf',
    pipeline: [
      { step: 'Parsed (LlamaParse)', duration: '14.7s' },
      { step: 'Chunked by structure', duration: '0.2s' },
      { step: 'Embedded', duration: '2.1s' },
      { step: 'Indexed in Pinecone', duration: '0.4s' },
    ],
    chunkPreview: [
      {
        location: 'p.1 · Investment income',
        text: 'Box 24 Actual amount of eligible dividends 4,120.00 · Box 25 Taxable amount 5,685.60…',
      },
    ],
    usedBy: [],
  },
  {
    id: 'doc_c90d5e3a',
    name: '2024_Brokerage_Annual_Statement.pdf',
    pages: 11,
    chunks: null,
    uploadedAt: 'Sep 22, 10:02 UTC',
    uploadedAtFull: 'Sep 22, 2026 10:02:11 UTC',
    status: 'processing',
    statusNote: 'Embedding 18/31 chunks',
    size: '4.6 MB',
    sha256: '5d3f88…a2e0',
    pipeline: [
      { step: 'Parsed (LlamaParse)', duration: '41.3s' },
      { step: 'Chunked by structure', duration: '0.3s' },
      { step: 'Embedding 18/31', duration: '…' },
    ],
    chunkPreview: [],
    usedBy: [],
  },
  {
    id: 'doc_e2f6b804',
    name: 'receipt_photo_blurry.pdf',
    pages: null,
    chunks: null,
    uploadedAt: 'Sep 22, 10:05 UTC',
    uploadedAtFull: 'Sep 22, 2026 10:05:52 UTC',
    status: 'failed',
    statusNote: 'Parse failed: no text layer recovered',
    size: '1.3 MB',
    sha256: 'e61b0d…4c73',
    pipeline: [],
    chunkPreview: [],
    usedBy: [],
  },
];

const FILTERS: { id: 'all' | DocStatus; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'processing', label: 'Processing' },
  { id: 'indexed', label: 'Indexed' },
  { id: 'failed', label: 'Failed' },
];

function statusCell(doc: Doc) {
  if (doc.status === 'indexed') return <StatusPill variant="success">Indexed</StatusPill>;
  if (doc.status === 'processing') {
    return (
      <>
        <StatusPill variant="accent">
          <span className="documents__spinner" aria-hidden="true" /> Processing
        </StatusPill>
        <div className="documents__status-note mono">{doc.statusNote}</div>
      </>
    );
  }
  return (
    <>
      <StatusPill variant="error">Failed</StatusPill>
      <div className="documents__status-note documents__status-note--error mono">
        {doc.statusNote} · <a href="#retry">Retry</a>
      </div>
    </>
  );
}

export function Documents() {
  const [filter, setFilter] = useState<'all' | DocStatus>('all');
  const [selectedId, setSelectedId] = useState(DOCS[0].id);

  const rows = filter === 'all' ? DOCS : DOCS.filter((d) => d.status === filter);
  const count = (id: 'all' | DocStatus) => (id === 'all' ? DOCS.length : DOCS.filter((d) => d.status === id).length);
  const indexedChunks = DOCS.reduce((sum, d) => sum + (d.status === 'indexed' ? d.chunks ?? 0 : 0), 0);
  const selected = DOCS.find((d) => d.id === selectedId) ?? DOCS[0];

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
              Parser: LlamaParse · Embeddings: text-embedding-3-small · Vector index: Pinecone /
              tax-docs
            </p>
          </div>
          <div className="documents__upload">
            <button type="button" className="btn btn-primary">
              <UploadIcon size={14} /> Upload document
            </button>
            <span className="mono">PDF · multi-page supported</span>
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

          <aside className="panel documents__detail">
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
          </aside>
        </div>
      </div>
    </div>
  );
}
