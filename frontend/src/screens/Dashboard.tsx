import { Link } from 'react-router';
import { StatusPill } from '../components/StatusPill';
import { RefreshIcon, UploadIcon } from '../components/Icons';
import './Dashboard.css';

const STAT_TILES = [
  {
    label: 'Documents indexed',
    value: '1,428',
    sub: '+14 today · 11,840 vector chunks',
    pill: { variant: 'success' as const, text: '99.8% HEALTH' },
    barPct: 99,
    barColor: 'success' as const,
  },
  {
    label: 'Needs review',
    value: '3',
    sub: '2 low-confidence citations · 1 schema drift',
    pill: { variant: 'warning' as const, text: 'REQUIRES ATTENTION' },
    barPct: 20,
    barColor: 'warning' as const,
  },
  {
    label: 'Confidence drop-rate',
    value: '3.2%',
    sub: '-0.8% vs 7-day baseline (threshold 5.0%)',
    pill: { variant: 'accent' as const, text: 'WITHIN SPEC' },
    barPct: 64,
    barColor: 'accent' as const,
  },
  {
    label: 'Golden-set eval score',
    value: '94.6%',
    sub: '189/200 eval pass · tax citation benchmark',
    pill: { variant: 'success' as const, text: 'PASSING EVAL' },
    barPct: 95,
    barColor: 'success' as const,
  },
];

const NEEDS_ATTENTION = [
  {
    name: '2023_Form_1065_K1_ApexHoldings.pdf',
    chunk: 'Chunk #41-43',
    timestamp: '2024-04-18 14:22:09 UTC',
    reason: 'Box 20 Code Z unmapped footnote: potential Section 199A qualification discrepancy',
    flag: 'Confidence 62%',
    action: 'Verify citation',
  },
  {
    name: 'Q4_State_Nexus_Apportionment_Schedule.xlsx',
    chunk: 'Chunk #12',
    timestamp: '2024-04-18 11:05:44 UTC',
    reason: 'Disputed payroll factor: OCR digit mismatch in California column C ($1,248,500.00 vs $1,248,500.80)',
    flag: '$0.80 mismatch',
    action: 'Inspect discrepancy',
  },
  {
    name: 'Depreciation_MACRS_Asset_Disposal_Batch_04.pdf',
    chunk: 'Chunk #88',
    timestamp: '2024-04-17 19:40:12 UTC',
    reason: 'Section 179 recapture rule ambiguity on dual-use commercial vehicle disposal',
    flag: 'Sign-off req',
    action: 'Review note',
  },
];

const RECENT_ACTIVITY = [
  {
    kind: 'POST',
    desc: '/ledger/entries — Deprec. Sec 179 recapture',
    source: 'Form 4562 Sch 1',
    amount: '$142,850.00',
  },
  {
    kind: 'QUERY',
    desc: 'What was the total non-deductible meals expense?',
    source: 'GL_Expense_Ledger_Q3.csv',
    amount: '—',
  },
  {
    kind: 'POST',
    desc: '/ledger/entries — State franchise tax accrual',
    source: 'DE_Franchise_Return.pdf',
    amount: '$18,450.00',
  },
  {
    kind: 'QUERY',
    desc: 'Extract foreign tax credits reported on Form 1118',
    source: 'Form 1118',
    amount: '—',
  },
];

export function Dashboard() {
  return (
    <div className="dashboard">
      <div className="dashboard__topbar">
        <span className="dashboard__breadcrumb">
          Ledger Assistant / <span>Proof of Rigor &amp; Ingestion Health</span>
        </span>
        <div className="dashboard__topbar-actions">
          <button type="button" className="dashboard__icon-btn">
            <RefreshIcon size={14} /> Refresh
          </button>
          <span className="mono dashboard__clock">14:32:08 UTC</span>
          <span className="dashboard__avatar" aria-hidden="true" />
        </div>
      </div>

      <div className="dashboard__body">
        <div className="dashboard__header">
          <div>
            <h1 className="dashboard__title">
              Dashboard{' '}
              <span className="status-pill status-pill--accent" style={{ marginLeft: 10 }}>
                STABLE / AUDIT ACTIVE
              </span>
            </h1>
            <p className="dashboard__subtitle">
              Document ingestion health, real-time citation accuracy, and computed ledger
              postings
            </p>
          </div>
          <div className="dashboard__header-actions">
            <button type="button" className="btn btn-secondary">
              <UploadIcon size={14} /> Export run log
            </button>
            <Link to="/chat" className="btn btn-primary">
              Ask Assistant <span className="mono">⌘K</span>
            </Link>
          </div>
        </div>

        <div className="dashboard__stats">
          {STAT_TILES.map((tile) => (
            <div className="stat-tile" key={tile.label}>
              <div className="stat-tile__head">
                <span className="stat-tile__label mono">{tile.label.toUpperCase()}</span>
                <StatusPill variant={tile.pill.variant}>{tile.pill.text}</StatusPill>
              </div>
              <div className="stat-tile__value mono">{tile.value}</div>
              <div className="stat-tile__sub">{tile.sub}</div>
              <div className="stat-tile__bar">
                <div
                  className={`stat-tile__bar-fill stat-tile__bar-fill--${tile.barColor}`}
                  style={{ width: `${tile.barPct}%` }}
                />
              </div>
            </div>
          ))}
        </div>

        <div className="dashboard__grid">
          <div className="dashboard__main-col">
            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">
                  Needs Attention{' '}
                  <span className="status-pill status-pill--warning" style={{ marginLeft: 8 }}>
                    3 Flagged
                  </span>
                </h2>
                <span className="panel__hint">
                  Deterministic verification required before ledger balance posting
                </span>
              </div>
              <ul className="attention-list">
                {NEEDS_ATTENTION.map((row) => (
                  <li className="attention-list__row" key={row.name}>
                    <div className="attention-list__main">
                      <div className="attention-list__top">
                        <span className="attention-list__name">{row.name}</span>
                        <span className="attention-list__chunk mono">{row.chunk}</span>
                      </div>
                      <p className="attention-list__reason">
                        <span className="attention-list__flag">{row.flag}</span> {row.reason}
                      </p>
                    </div>
                    <div className="attention-list__side">
                      <span className="mono attention-list__ts">{row.timestamp}</span>
                      <Link to="/documents">{row.action} →</Link>
                    </div>
                  </li>
                ))}
              </ul>
            </section>

            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Recent Ledger Postings &amp; AI Queries</h2>
                <span className="status-pill status-pill--accent">STREAM LIVE</span>
              </div>
              <div className="scroll-x">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Description / Prompt reference</th>
                      <th>Source ref</th>
                      <th>Computed amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {RECENT_ACTIVITY.map((row) => (
                      <tr key={row.desc}>
                        <td>
                          {row.kind === 'POST' ? (
                            <span className="dashboard__kind dashboard__kind--post">POST</span>
                          ) : (
                            <span className="dashboard__kind">QUERY</span>
                          )}{' '}
                          {row.desc}
                        </td>
                        <td className="mono">{row.source}</td>
                        <td className="num">{row.amount}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Link className="panel__footer-link" to="/ledger">
                View immutable audit journal →
              </Link>
            </section>
          </div>

          <div className="dashboard__side-col">
            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Corpus &amp; Telemetry</h2>
                <span className="status-pill status-pill--success" style={{ padding: '2px 8px' }}>
                  ●
                </span>
              </div>
              <div className="telemetry">
                <div className="telemetry__row">
                  <span className="telemetry__label mono">TOTAL INGESTED DOCUMENTS</span>
                  <div className="telemetry__value mono">842 files</div>
                  <span className="status-pill status-pill--success">PARSED OK</span>
                </div>
                <div className="telemetry__row">
                  <span className="telemetry__label mono">VECTOR EMBEDDINGS</span>
                  <div className="telemetry__value mono">14,892 vectors</div>
                  <span className="telemetry__note mono">pgvector · text-embedding-3-large</span>
                </div>
                <div className="telemetry__row">
                  <span className="telemetry__label mono">LAST INGESTION RUN</span>
                  <div className="telemetry__value mono" style={{ fontSize: 14 }}>
                    2024-04-18 14:15:00 UTC
                  </div>
                  <span className="telemetry__note">17 minutes ago</span>
                </div>
                <div className="telemetry__split">
                  <div>
                    <span className="telemetry__label mono">RAG LATENCY</span>
                    <div className="telemetry__value mono" style={{ fontSize: 18 }}>
                      412ms
                    </div>
                    <span className="telemetry__note mono">p95: 580ms</span>
                  </div>
                  <div>
                    <span className="telemetry__label mono">CITATION COVERAGE</span>
                    <div
                      className="telemetry__value mono"
                      style={{ fontSize: 18, color: 'var(--color-success)' }}
                    >
                      99.4%
                    </div>
                    <span className="telemetry__note">strict bounds</span>
                  </div>
                </div>
                <div className="telemetry__chart">
                  <span className="telemetry__label mono">INGESTION THROUGHPUT (24H)</span>
                  <div className="telemetry__bars">
                    {[40, 55, 48, 62, 58, 70, 66, 78, 74, 82, 90, 48].map((h, i) => (
                      <span
                        key={i}
                        className={`telemetry__bar${i === 10 ? ' telemetry__bar--accent' : ''}${
                          i === 11 ? ' telemetry__bar--success' : ''
                        }`}
                        style={{ height: `${h}%` }}
                      />
                    ))}
                  </div>
                </div>
                <div className="telemetry__banner">
                  All sync pipelines deterministic &amp; operational
                </div>
              </div>
            </section>

            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Parser checksum</h2>
                <span className="mono panel__hint">SHA-256</span>
              </div>
              <div className="mono checksum-box">
                e83c072e9a2f1b4c8d5045a193fd3458bfa791244d2146820556f8f4a1329a1b
              </div>
              <div className="checksum-foot">
                <span>Root Merkle tree</span>
                <StatusPill variant="success">VERIFIED VALID</StatusPill>
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
