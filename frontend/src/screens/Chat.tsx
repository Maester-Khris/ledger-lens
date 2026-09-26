import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { ArrowUpIcon, SparkleIcon } from '../components/Icons';
import { Markdown } from '../components/Markdown';
import { ApprovalCard } from '../components/ApprovalCard';
import { StatusPill } from '../components/StatusPill';
import { type ChatEvent, type Citation, type ToolInvocationDto, fileUrl, listDocuments, streamChat, listToolInvocations } from '../api';
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
};

interface CitationCardProps {
  citation: Citation;
}

function CitationCard({ citation }: CitationCardProps) {
  const href = fileUrl(citation);
  return (
    <div className="citation-card">
      <div className="citation-card__head">
        <span className="citation-card__doc">{citation.document_title ?? citation.tool}</span>
        {citation.page !== undefined && (
          <span className="citation-card__loc">
            v{citation.version} · p.{citation.page}
            {citation.section ? ` · ${citation.section}` : ''}
          </span>
        )}
      </div>
      {citation.quote && <p className="mono citation-card__excerpt">{citation.quote}</p>}
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
  const [inputValue, setInputValue] = useState('');
  const [sessionId, setSessionId] = useState(newSessionId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [indexedCount, setIndexedCount] = useState<number | null>(null);

  const [approvals, setApprovals] = useState<ToolInvocationDto[]>([]);

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
      .then((docs) => setIndexedCount(docs.filter((d) => d.status === 'ready').length))
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
    setTurns((all) => [...all, { question, step: null, outcome: 'pending', text: '', citations: [] }]);
    const onEvent = (event: ChatEvent) => {
      if (event.type === 'progress') updateLast({ step: event.data.step });
      else if (event.type === 'error') updateLast({ outcome: 'error', text: event.data.text });
      else updateLast({ outcome: event.type, text: event.data.text, citations: event.data.citations });
    };
    try {
      await streamChat(sessionId, question, onEvent);
    } catch (error) {
      updateLast({ outcome: 'error', text: error instanceof Error ? error.message : 'Chat failed' });
    } finally {
      inputRef.current?.focus();
      refreshApprovals(sessionId);
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
          onClick={() => {
            setSessionId(newSessionId());
            setTurns([]);
            setApprovals([]);
          }}
        >
          + New session
        </button>
      </div>

      <div className="chat__scroll" ref={scrollRef}>
        <div className="chat__thread">
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
                  </>
                )}
              </div>
            </div>
          ))}
          {approvals.length > 0 && (
            <div className="chat__approvals">
              <span className="chat__approvals-label">Correction proposed in this session</span>
              {approvals.map((invocation) => (
                <ApprovalCard key={invocation.id} invocation={invocation} />
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
            Answers come only from your indexed contracts, every number is checked against the cited text, and the
            assistant says so when it can't find an answer.
          </div>
        </form>
      </div>
    </div>
  );
}
