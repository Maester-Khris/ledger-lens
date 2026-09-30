import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { type ConfigDto, type DocumentSummary, type StatsDto, getConfig, getStats, listDocuments, listPostings } from '../api';
import { StatusPill } from '../components/StatusPill';
import { type PostingView, toPostingView } from '../lib/postings';
import { evalScore, formatAgo, formatMs, formatPercent } from '../lib/stats';
import { formatUtc } from '../lib/time';
import './Dashboard.css';

const RECENT_POSTINGS = 5;
const CONTRACTS_SHOWN = 6;

interface DashboardData {
  stats: StatsDto;
  config: ConfigDto;
  documents: DocumentSummary[];
  postings: PostingView[];
  loadedAt: number;
}

interface StatTileProps {
  label: string;
  value: string;
  detail: string;
  tone?: 'warning';
  muted?: boolean;
  to?: string;
}

function StatTile({ label, value, detail, tone, muted, to }: StatTileProps) {
  const body = (
    <>
      <span className="stat-tile__label">{label}</span>
      <span className={`stat-tile__value mono${tone ? ` stat-tile__value--${tone}` : ''}`}>{value}</span>
      <span className="stat-tile__detail">{detail}</span>
    </>
  );
  const className = `stat-tile${muted ? ' stat-tile--muted' : ''}`;
  return to ? (
    <Link to={to} className={`${className} stat-tile--link`}>
      {body}
    </Link>
  ) : (
    <div className={className} aria-disabled={muted || undefined}>
      {body}
    </div>
  );
}

interface QueueRowProps {
  count: number;
  label: string;
  detail: string;
  to: string;
  action: string;
}

function QueueRow({ count, label, detail, to, action }: QueueRowProps) {
  return (
    <li className="queue__row">
      <span className={`queue__count mono${count === 0 ? ' queue__count--zero' : ''}`}>{count}</span>
      <div className="queue__text">
        <span className="queue__label">{label}</span>
        <span className="queue__detail">{detail}</span>
      </div>
      <Link to={to} className="queue__action">
        {action} →
      </Link>
    </li>
  );
}

interface TelemetryRowProps {
  label: string;
  value: string;
  note?: string;
}

function TelemetryRow({ label, value, note }: TelemetryRowProps) {
  return (
    <div className="telemetry__row">
      <dt>{label}</dt>
      <dd>
        <span className="mono">{value}</span>
        {note && <span className="telemetry__note">{note}</span>}
      </dd>
    </div>
  );
}

const DOC_STATUS: Record<DocumentSummary['status'], { variant: 'success' | 'accent' | 'warning'; label: string }> = {
  ready: { variant: 'success', label: 'Indexed' },
  processing: { variant: 'accent', label: 'Processing' },
  failed: { variant: 'warning', label: 'Failed' },
};

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getStats(), getConfig(), listDocuments(), listPostings({ limit: RECENT_POSTINGS })])
      .then(([stats, config, documents, page]) => {
        if (!cancelled) setData({ stats, config, documents, postings: page.items.map(toPostingView), loadedAt: Date.now() });
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="dashboard">
      <div className="dashboard__topbar">
        <span className="dashboard__breadcrumb">Dashboard</span>
        <Link to="/" className="dashboard__home-link">← Back home</Link>
      </div>

      <div className="dashboard__body">
        <div className="dashboard__header">
          <div>
            <h1 className="dashboard__title">Dashboard</h1>
            <p className="dashboard__subtitle">What needs a person, how the corpus looks, and what posted recently.</p>
          </div>
          <Link to="/chat" className="btn btn-primary">
            Ask the assistant
          </Link>
        </div>

        {error && (
          <div className="panel dashboard__error" role="alert">
            <strong>Couldn't reach the API.</strong> {error}. Start the backend with{' '}
            <code className="mono">uvicorn app.main:app</code> and reload.
          </div>
        )}

        {!error && data === null && <p className="dashboard__loading">Loading…</p>}

        {data && (
          <>
            <div className="dashboard__stats">
              <StatTile
                label="Documents indexed"
                value={`${data.stats.documents.indexed} / ${data.stats.documents.total}`}
                detail={`${data.stats.documents.indexed_chunks.toLocaleString('en-US')} chunks indexed`}
              />
              <StatTile
                label="Needs review"
                value={String(data.stats.reviews_pending + data.stats.approvals_pending)}
                detail={`${data.stats.reviews_pending} fields · ${data.stats.approvals_pending} corrections`}
                tone={data.stats.reviews_pending + data.stats.approvals_pending > 0 ? 'warning' : undefined}
                to="/review"
              />
              <StatTile label="Confidence drop-rate" value="—" detail="Rolling 7-day window · not tracked in this demo" muted />
              <StatTile
                label="Golden-set eval"
                value={data.stats.eval ? formatPercent(evalScore(data.stats.eval)) : '—'}
                detail={
                  data.stats.eval
                    ? `${data.stats.eval.cases} cases · numbers ${formatPercent(data.stats.eval.numbers_ok)} · refusals ${formatPercent(data.stats.eval.refusal_ok)} · citations ${formatPercent(data.stats.eval.citation_hit)}`
                    : 'No golden-set run for the running configuration'
                }
                muted={!data.stats.eval}
              />
            </div>

            <div className="dashboard__grid">
              <div className="dashboard__col">
                <section className="panel">
                  <div className="panel__head">
                    <h2 className="panel__title">Needs a person</h2>
                  </div>
                  <ul className="queue">
                    <QueueRow
                      count={data.stats.reviews_pending}
                      label="extracted fields to review"
                      detail="Held back because the quote couldn't be grounded, a validator failed, or the page was hard to read."
                      to="/review"
                      action="Review fields"
                    />
                    <QueueRow
                      count={data.stats.approvals_pending}
                      label="fee corrections to approve"
                      detail="Billing reconciliation found a gap. Nothing posts to the ledger until someone approves it."
                      to="/review#approvals"
                      action="Review corrections"
                    />
                    <QueueRow
                      count={data.stats.documents.failed}
                      label="documents failed ingestion"
                      detail="Usually a scanned PDF without a text layer."
                      to="/documents"
                      action="Open documents"
                    />
                  </ul>
                </section>

                <section className="panel">
                  <div className="panel__head">
                    <h2 className="panel__title">Recent postings</h2>
                  </div>
                  {data.postings.length === 0 ? (
                    <p className="dashboard__empty">No postings yet. Approved corrections and fee runs will appear here.</p>
                  ) : (
                    <div className="scroll-x">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Created</th>
                            <th>Description</th>
                            <th>Source</th>
                            <th style={{ textAlign: 'right' }}>Amount</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.postings.map((p) => (
                            <tr key={p.id}>
                              <td className="mono">{formatUtc(p.createdAt)}</td>
                              <td>
                                <Link to={`/ledger?posting=${p.id}`}>{p.description}</Link>
                              </td>
                              <td className="mono">{p.source}</td>
                              <td className="num">{p.amount}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <Link className="panel__footer-link" to="/ledger">
                    Open the ledger →
                  </Link>
                </section>
              </div>

              <div className="dashboard__col">
                <section className="panel">
                  <div className="panel__head">
                    <h2 className="panel__title">Corpus &amp; telemetry</h2>
                  </div>
                  <dl className="telemetry">
                    <TelemetryRow
                      label="Documents"
                      value={`${data.stats.documents.total}`}
                      note={`${data.stats.documents.processing} processing · ${data.stats.documents.failed} failed`}
                    />
                    <TelemetryRow
                      label="Indexed chunks"
                      value={data.stats.documents.indexed_chunks.toLocaleString('en-US')}
                      note={data.config.vector_store}
                    />
                    <TelemetryRow
                      label="Embeddings"
                      value={data.config.embedding_model}
                      note={`${data.config.embedding_dimensions} dimensions`}
                    />
                    <TelemetryRow label="Chat model" value={data.config.chat_model} />
                    <TelemetryRow
                      label="Last ingestion"
                      value={data.stats.last_ingestion_at ? formatUtc(data.stats.last_ingestion_at) : '—'}
                      note={data.stats.last_ingestion_at ? formatAgo(data.stats.last_ingestion_at, data.loadedAt) : undefined}
                    />
                    <TelemetryRow
                      label="Answer latency (7 d)"
                      value={`p50 ${formatMs(data.stats.chat.latency_p50_ms)} · p95 ${formatMs(data.stats.chat.latency_p95_ms)}`}
                      note={`${data.stats.chat.turns_7d} chat turns`}
                    />
                    <TelemetryRow
                      label="Citation coverage"
                      value={data.stats.eval ? formatPercent(data.stats.eval.citation_hit) : '—'}
                      note="golden set"
                    />
                  </dl>
                </section>

                <section className="panel">
                  <div className="panel__head">
                    <h2 className="panel__title">Contracts</h2>
                  </div>
                  {data.documents.length === 0 ? (
                    <p className="dashboard__empty">
                      No contracts yet. <Link to="/documents">Upload one</Link> to start.
                    </p>
                  ) : (
                    <ul className="contract-list">
                      {data.documents.slice(0, CONTRACTS_SHOWN).map((doc) => (
                        <li key={doc.id} className="contract-list__row">
                          <span className="contract-list__title" title={doc.title}>
                            {doc.title}
                          </span>
                          <StatusPill variant={DOC_STATUS[doc.status].variant}>{DOC_STATUS[doc.status].label}</StatusPill>
                        </li>
                      ))}
                    </ul>
                  )}
                  <Link className="panel__footer-link" to="/documents">
                    All documents →
                  </Link>
                </section>
              </div>
            </div>
          </>
        )}

        <Link to="/" className="dashboard__home-link dashboard__home-link--bottom">← Back home</Link>
      </div>
    </div>
  );
}
