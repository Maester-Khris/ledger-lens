import { useState } from 'react';
import { Link } from 'react-router';
import { ArrowUpIcon, SparkleIcon } from '../components/Icons';
import { StatusPill } from '../components/StatusPill';
import { type ChatEvent, type Citation, fileUrl, streamChat } from '../api';
import './Chat.css';

const SUGGESTED_QUESTIONS = [
  'What is the fee schedule in the Tremblay agreement?',
  'How much notice is needed to terminate the Tremblay agreement?',
  'Which law governs the Tremblay agreement?',
  'What is the Calamos fund’s rate in excess of $26 billion?',
];

type AssistantHeadProps = {
  label: string;
  variant: 'neutral' | 'accent' | 'warning';
  detail?: string;
};

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

export function Chat() {
  const [inputValue, setInputValue] = useState('');
  const [sessionId, setSessionId] = useState(newSessionId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const busy = turns.some((t) => t.outcome === 'pending');

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
                Indexed contracts
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
          }}
        >
          + New session
        </button>
      </div>

      <div className="chat__scroll">
        <div className="chat__thread">
          {turns.length === 0 && (
            <div className="chat__prompts">
              <span className="chat__prompts-label mono">Suggested questions</span>
              <div className="chat__prompt-chips">
                {SUGGESTED_QUESTIONS.map((question) => (
                  <button type="button" className="chat__prompt-chip" key={question} onClick={() => ask(question)}>
                    {question}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((turn, index) => (
            <div key={index}>
              <div className="chat__turn chat__turn--user">
                <div className="chat__bubble--user">{turn.question}</div>
              </div>
              <div className="chat__turn chat__turn--assistant" aria-live="polite">
                {turn.outcome === 'pending' && <AssistantHead label={turn.step ?? 'thinking'} variant="accent" />}
                {turn.outcome === 'answer' && (
                  <>
                    <AssistantHead label="Answer" variant="neutral" detail={`${turn.citations.length} citation(s)`} />
                    <p className="chat__prose">{turn.text}</p>
                    {turn.citations.map((c) => (
                      <CitationCard key={c.id} citation={c} />
                    ))}
                  </>
                )}
                {(turn.outcome === 'refused' || turn.outcome === 'error') && (
                  <>
                    <AssistantHead label={turn.outcome === 'refused' ? 'No answer' : 'Error'} variant="warning" />
                    <p className="chat__prose">{turn.text}</p>
                  </>
                )}
              </div>
            </div>
          ))}
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
              type="text"
              className="chat__composer-input"
              placeholder="Ask about your indexed contracts…"
              aria-label="Ask about your indexed contracts"
              value={inputValue}
              disabled={busy}
              onChange={(event) => setInputValue(event.target.value)}
            />
            <button type="submit" className="chat__composer-send" aria-label="Send message" disabled={busy}>
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
