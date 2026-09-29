import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ArrowUpIcon, SparkleIcon } from '../components/Icons';
import { Markdown } from '../components/Markdown';
import { ApprovalCard } from '../components/ApprovalCard';
import { StatusPill } from '../components/StatusPill';
import { type ChatEvent, type Citation, type ToolInvocationDto, type DocumentSummary, type UnvalidatedDto, fileUrl, listDocuments, streamChat, listToolInvocations } from '../api';
import { DocumentCards } from '../components/workspace/DocumentCards';
import { ScopeChip } from '../components/workspace/ScopeChip';
import { DocumentPanel, type PanelTab } from '../components/workspace/DocumentPanel';
import { ContractProfile } from '../components/workspace/ContractProfile';
import { BillingReconciliation } from '../components/workspace/BillingReconciliation';
import { AuditLog } from '../components/workspace/AuditLog';
import { LedgerTimeline } from '../components/workspace/LedgerTimeline';
import { UnvalidatedNotice } from '../components/workspace/UnvalidatedNotice';
import '../components/workspace/Workspace.css';
import './Chat.css';

const SUGGESTED_QUESTIONS = [
  'What is the fee schedule in the Tremblay agreement?',
  'How much notice is needed to terminate the Tremblay agreement?',
  'Which law governs the Tremblay agreement?',
  'What is the Calamos fund’s rate in excess of $26 billion?',
];

interface AssistantHeadProps {
  label: string;
  variant: 'neutral' | 'accent' | 'warning';
  detail?: string;
}

function AssistantHead({ label, variant, detail }: AssistantHeadProps) {
  return (
    <div className="chat__assistant-head">
      <SparkleIcon size={15} className="chat__sparkle" />
      <StatusPill variant={variant}>{label}</StatusPill>
      {detail && <span className="chat__tag mono">{detail}</span>}
    </div>
  );
}

type Turn = {
  question: string;
  step: string | null;
  outcome: 'pending' | 'answer' | 'refused' | 'error';
  text: string;
  citations: Citation[];
  unvalidated: UnvalidatedDto[];
};

interface CitationCardProps {
  citation: Citation;
}

function CitationCard({ citation }: CitationCardProps) {
  const href = fileUrl(citation);
  return (
    <div className="citation-card">
      <div className="citation-card__head">
        {citation.kind === 'system' ? (
          <span className="citation-card__doc">System · {citation.source}</span>
        ) : (
          <span className="citation-card__doc">{citation.document_title ?? citation.tool}</span>
        )}
        {citation.page !== undefined && (
          <span className="citation-card__loc">
            v{citation.version} · p.{citation.page}
            {citation.section ? ` · ${citation.section}` : ''}
          </span>
        )}
      </div>
      {citation.quote && <p className="mono citation-card__excerpt">{citation.quote}</p>}
      {citation.detail && <p className="mono citation-card__excerpt">{citation.detail}</p>}
      <div className="citation-card__foot">
        <span className="mono">{citation.id}</span>
        {href && (
          <a href={href} target="_blank" rel="noreferrer">
            Open page →
          </a>
        )}
      </div>
    </div>
  );
}

function newSessionId(): string {
  return `ses_${crypto.randomUUID().slice(0, 8)}`;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function indexedLabel(count: number | null): string {
  if (count === null) return 'Indexed contracts';
  return `${count} indexed contract${count === 1 ? '' : 's'}`;
}

export function Chat() {
  const [searchParams] = useSearchParams();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [scopeId, setScopeId] = useState<string | null>(searchParams.get('document'));
  const [cardsOpen, setCardsOpen] = useState(true);
  const [panelOpen, setPanelOpen] = useState(false);
  const scoped = documents.find((d) => d.id === scopeId) ?? null;
  const [inputValue, setInputValue] = useState('');
  const [sessionId, setSessionId] = useState(newSessionId);
  const [auditKey, setAuditKey] = useState(0);
  const [ledgerKey, setLedgerKey] = useState(0);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [indexedCount, setIndexedCount] = useState<number | null>(null);

  const tabs: PanelTab[] = [
    ...(scopeId ? [
      { id: 'profile', label: 'Profile', content: <ContractProfile documentId={scopeId} /> },
      { id: 'billing', label: 'Billing reconciliation', content: <BillingReconciliation documentId={scopeId} /> },
      { id: 'ledger', label: 'Ledger', content: <LedgerTimeline documentId={scopeId} refreshKey={ledgerKey} /> },
    ] : []),
    { id: 'audit', label: 'Audit trail', content: <AuditLog sessionId={sessionId} refreshKey={auditKey} /> },
  ];

  const [approvals, setApprovals] = useState<ToolInvocationDto[]>([]);

  const startConversation = (nextScope: string | null) => {
    setScopeId(nextScope);
    setSessionId(newSessionId());
    setTurns([]);
    setApprovals([]);
    setCardsOpen(true);
  };

  const refreshApprovals = useCallback((session: string) => {
    listToolInvocations({ limit: 50 })
      .then((rows) => setApprovals(rows.filter((row) => row.session_id === session && row.approval_required)))
      .catch(() => setApprovals([]));
  }, []);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = turns.some((t) => t.outcome === 'pending');

  useEffect(() => {
    listDocuments()
      .then((docs) => { setDocuments(docs); setIndexedCount(docs.filter((d) => d.status === 'ready').length); })
      .catch(() => setIndexedCount(null));
  }, []);

  useEffect(() => {
    const scroller = scrollRef.current;
    scroller?.scrollTo({ top: scroller.scrollHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  }, [turns]);

  const updateLast = (patch: Partial<Turn>) =>
    setTurns((all) => all.map((t, i) => (i === all.length - 1 ? { ...t, ...patch } : t)));

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setInputValue('');
    setCardsOpen(false);
    setTurns((all) => [...all, { question, step: null, outcome: 'pending', text: '', citations: [], unvalidated: [] }]);
    const onEvent = (event: ChatEvent) => {
      if (event.type === 'progress') updateLast({ step: event.data.step });
      else if (event.type === 'unvalidated') setTurns((all) => all.map((t, i) => (i === all.length - 1 ? { ...t, unvalidated: [...t.unvalidated, event.data] } : t)));
      else if (event.type === 'error') updateLast({ outcome: 'error', text: event.data.text });
      else updateLast({ outcome: event.type, text: event.data.text, citations: event.data.citations });
    };
    try {
      await streamChat(sessionId, question, onEvent, { documentId: scopeId ?? undefined });
    } catch (error) {
      updateLast({ outcome: 'error', text: error instanceof Error ? error.message : 'Chat failed' });
    } finally {
      inputRef.current?.focus();
      refreshApprovals(sessionId);
      setAuditKey((k) => k + 1);
    }
  };

  return (
    <div className="chat">
      <div className="chat__header">
        <div className="chat__header-main">
          <span className="chat__breadcrumb">Chat</span>
          <div className="chat__title-row">
            <h1 className="chat__title">Ask your contracts</h1>
            <Link to="/documents" className="chat__indexed-pill">
              <StatusPill variant="accent" dot>
                {indexedLabel(indexedCount)}
              </StatusPill>
            </Link>
            <span className="chat__session mono">session {sessionId}</span>
          </div>
        </div>
        <button
          type="button"
          className="btn btn-secondary chat__new-session"
          onClick={() => startConversation(scopeId)}
        >
          + New session
        </button>
      </div>

      <div className={`ws-layout${tabs.length ? ' ws-layout--with-panel' : ''}`}>
        <div className="chat__column">
          <div className="chat__scroll" ref={scrollRef}>
            <div className="chat__thread">
              {cardsOpen ? (
                <DocumentCards documents={documents} selectedId={scopeId} onSelect={(id) => id !== scopeId && startConversation(id)} />
              ) : (
                <ScopeChip title={scoped?.title ?? null} onOpen={() => { setCardsOpen(true); setPanelOpen(true); }} onClear={() => startConversation(null)} />
              )}
              {turns.length === 0 && (
                <div className="chat__prompts">
                  <span className="chat__prompts-label">Suggested questions</span>
                  <div className="chat__prompt-chips">
                    {SUGGESTED_QUESTIONS.map((question) => (
                      <button type="button" className="chat__prompt-chip" key={question} onClick={() => void ask(question)}>
                        {question}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {turns.map((turn, index) => (
                <div className="chat__exchange" key={index}>
                  <div className="chat__turn chat__turn--user">
                    <div className="chat__bubble--user">{turn.question}</div>
                  </div>
                  <div className="chat__turn chat__turn--assistant" aria-live="polite">
                    {turn.outcome === 'pending' && <AssistantHead label={turn.step ?? 'thinking'} variant="accent" />}
                    {turn.unvalidated.map((notice, i) => (
                      <UnvalidatedNotice key={i} notice={notice} />
                    ))}
                    {turn.outcome === 'answer' && (
                      <>
                        <AssistantHead label="Answer" variant="neutral" detail={`${turn.citations.length} citation(s)`} />
                        <Markdown className="chat__prose" text={turn.text} />
                        {turn.citations.length > 0 && (
                          <div className="chat__citations">
                            {turn.citations.map((c) => (
                              <CitationCard key={c.id} citation={c} />
                            ))}
                          </div>
                        )}
                      </>
                    )}
                    {(turn.outcome === 'refused' || turn.outcome === 'error') && (
                      <>
                        <AssistantHead label={turn.outcome === 'refused' ? 'No answer' : 'Error'} variant="warning" />
                        <Markdown className="chat__prose" text={turn.text} />
                        {turn.citations.length > 0 && (
                          <div className="chat__citations">
                            {turn.citations.map((c) => (
                              <CitationCard key={c.id} citation={c} />
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              ))}
              {approvals.length > 0 && (
                <div className="chat__approvals">
                  <span className="chat__approvals-label">Correction proposed in this session</span>
                  {approvals.map((invocation) => (
                    <ApprovalCard key={invocation.id} invocation={invocation} onDecided={() => { refreshApprovals(sessionId); setLedgerKey((k) => k + 1); setAuditKey((k) => k + 1); }} />
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="chat__composer">
            <form
              className="chat__composer-inner"
              onSubmit={(event) => {
                event.preventDefault();
                void ask(inputValue);
              }}
            >
              <div className="chat__composer-bar">
                <input
                  ref={inputRef}
                  type="text"
                  className="chat__composer-input"
                  placeholder="Ask about your indexed contracts…"
                  aria-label="Ask about your indexed contracts"
                  value={inputValue}
                  onChange={(event) => setInputValue(event.target.value)}
                />
                <button
                  type="submit"
                  className="chat__composer-send"
                  aria-label="Send message"
                  disabled={busy || !inputValue.trim()}
                >
                  <ArrowUpIcon size={16} />
                </button>
              </div>
              <div className="chat__composer-foot">
                Every number in an answer traces to the page it's cited from, checked before you see it — and the
                assistant says so when it can't find one.
              </div>
            </form>
          </div>
        </div>
        {(panelOpen || window.matchMedia('(min-width: 1100px)').matches) && <DocumentPanel tabs={tabs} />}
      </div>
    </div>
  );
}
