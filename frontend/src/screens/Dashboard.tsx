import { useEffect, useState } from 'react';
import { getConfig, getStats, type ConfigDto, type StatsDto } from '../api';
import { evalScore, formatAgo, formatMs, formatPercent } from '../lib/stats';
import './Dashboard.css';

export function Dashboard() {
  const [stats, setStats] = useState<StatsDto | null>(null);
  const [config, setConfig] = useState<ConfigDto | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(console.error);
    getConfig().then(setConfig).catch(console.error);
  }, []);

  if (!stats || !config) {
    return <div className="dashboard dashboard--loading">Loading...</div>;
  }

  const liveConfigMismatch = stats.eval && config.eval_config_hash !== stats.eval.config_hash;

  return (
    <div className="dashboard">
      <h1 className="dashboard__title">Operations</h1>

      <div className="dashboard__grid">
        <div className="tile">
          <h2 className="tile__title">Human Review</h2>
          <div className="tile__stat">
            <span className="tile__stat-value">{stats.reviews_pending}</span>
            <span className="tile__stat-label">contracts</span>
          </div>
          <div className="tile__stat">
            <span className="tile__stat-value">{stats.approvals_pending}</span>
            <span className="tile__stat-label">tool calls</span>
          </div>
        </div>

        <div className="tile">
          <h2 className="tile__title">Corpus</h2>
          <div className="tile__stat">
            <span className="tile__stat-value">{stats.documents.indexed}</span>
            <span className="tile__stat-label">documents</span>
          </div>
          <div className="tile__stat">
            <span className="tile__stat-value">{stats.documents.indexed_chunks.toLocaleString()}</span>
            <span className="tile__stat-label">vectors</span>
          </div>
          <div className="tile__meta">
            {(stats.documents.processing > 0 || stats.documents.failed > 0) && (
              <p>{stats.documents.processing} processing, {stats.documents.failed} failed</p>
            )}
            <p>Last ingested {stats.last_ingestion_at ? formatAgo(stats.last_ingestion_at) : 'never'}</p>
          </div>
        </div>

        <div className="tile">
          <h2 className="tile__title">Chat (7d)</h2>
          <div className="tile__stat">
            <span className="tile__stat-value">{stats.chat.turns_7d}</span>
            <span className="tile__stat-label">turns</span>
          </div>
          <div className="tile__stat">
            <span className="tile__stat-value">{formatMs(stats.chat.latency_p50_ms)}</span>
            <span className="tile__stat-label">p50</span>
          </div>
          <div className="tile__stat">
            <span className="tile__stat-value">{formatMs(stats.chat.latency_p95_ms)}</span>
            <span className="tile__stat-label">p95</span>
          </div>
        </div>

        <div className={`tile ${liveConfigMismatch ? 'tile--warn' : ''}`}>
          <h2 className="tile__title">Eval Golden Set</h2>
          {stats.eval ? (
            <>
              <div className="tile__stat">
                <span className="tile__stat-value">{formatPercent(evalScore(stats.eval))}</span>
                <span className="tile__stat-label">pass</span>
              </div>
              <div className="tile__meta">
                <p>N={stats.eval.cases}</p>
                <p>{formatPercent(stats.eval.numbers_ok)} amounts</p>
                <p>{formatPercent(stats.eval.refusal_ok)} boundaries</p>
                <p>{formatPercent(stats.eval.citation_hit)} citations</p>
                {liveConfigMismatch && (
                  <p className="tile__warn-text">⚠️ Live model differs from report</p>
                )}
              </div>
            </>
          ) : (
            <p className="tile__empty">No report for current config</p>
          )}
        </div>
      </div>

      <div className="telemetry">
        <h2 className="telemetry__title">Deployment Configuration</h2>
        <dl className="telemetry__list">
          <dt>Chat Agent</dt>
          <dd>{config.chat_model}</dd>

          <dt>Data Extraction</dt>
          <dd>{config.extraction_model}</dd>

          <dt>Embeddings</dt>
          <dd>{config.embedding_model} ({config.embedding_dimensions}d)</dd>

          <dt>Ingestion Parser</dt>
          <dd>{config.parser}</dd>

          <dt>PII Vault</dt>
          <dd>{config.pii}</dd>

          <dt>Retrieval</dt>
          <dd>
            {config.vector_store}<br />
            (fusion top-K: {config.retrieval.search_candidates}, dense min: {config.retrieval.min_dense_similarity})
          </dd>
        </dl>
      </div>
    </div>
  );
}
