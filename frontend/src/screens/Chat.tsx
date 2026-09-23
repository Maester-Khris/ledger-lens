import { useState } from 'react';
import { Link } from 'react-router';
import { ArrowUpIcon, CheckIcon, SparkleIcon } from '../components/Icons';
import { StatusPill } from '../components/StatusPill';
import './Chat.css';

const SUGGESTED_QUESTIONS = [
  'What was my total reported income on the 2024 T4?',
  'How much income tax was deducted on my W-2?',
  'Post my T4 total income to the ledger',
  'What was my charitable donation amount in 2024?',
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

export function Chat() {
  const [inputValue, setInputValue] = useState('');
  // ponytail: local toggle only so both footer states of the tool card can be shown; wired to POST /postings later
  const [posted, setPosted] = useState(false);

  return (
    <div className="chat">
      <div className="chat__header">
        <div className="chat__header-main">
          <span className="chat__breadcrumb">Chat</span>
          <div className="chat__title-row">
            <h1 className="chat__title">Ask your documents</h1>
            <Link to="/documents" className="chat__indexed-pill">
              <StatusPill variant="accent" dot>
                3 documents indexed · 45 chunks
              </StatusPill>
            </Link>
            <span className="chat__session mono">session ses_5d21</span>
          </div>
        </div>
        <button type="button" className="btn btn-secondary chat__new-session">
          + New session
        </button>
      </div>

      <div className="chat__scroll">
        <div className="chat__thread">
          <div className="chat__prompts">
            <span className="chat__prompts-label mono">Suggested questions</span>
            <div className="chat__prompt-chips">
              {SUGGESTED_QUESTIONS.map((question) => (
                <button
                  type="button"
                  className="chat__prompt-chip"
                  key={question}
                  onClick={() => setInputValue(question)}
                >
                  {question}
                </button>
              ))}
            </div>
          </div>

          {/* Turn 1 — retrieval answer with citation */}
          <div className="chat__turn chat__turn--user">
            <div className="chat__bubble--user">
              What was my total reported employment income on the 2024 T4?
            </div>
          </div>

          <div className="chat__turn chat__turn--assistant">
            <AssistantHead label="Answer" variant="neutral" detail="1 citation" />
            <p className="chat__prose">
              Your total reported employment income on the 2024 T4 is{' '}
              <span className="mono chat__figure">94,500.00 CAD</span> (Box 14, Acme Corp
              Technologies).
            </p>
            <div className="citation-card">
              <div className="citation-card__head">
                <span className="citation-card__doc">2024_T4_AcmeCorp.pdf</span>
                <span className="citation-card__loc">p.1 · Employment income</span>
                <span className="citation-card__score mono">relevance 0.89</span>
              </div>
              <p className="mono citation-card__excerpt">
                Box 14 Employment income 94,500.00 · Box 22 Income tax deducted 18,212.40
              </p>
              <div className="citation-card__foot">
                <span className="mono">doc_7f3a21c9 · chunk 3 of 14</span>
                <Link to="/documents">Open in Documents →</Link>
              </div>
            </div>
          </div>

          {/* Turn 2 — deterministic tool call, logged */}
          <div className="chat__turn chat__turn--user">
            <div className="chat__bubble--user">
              Compute my total reported income from the T4 and prepare it for the ledger.
            </div>
          </div>

          <div className="chat__turn chat__turn--assistant">
            <AssistantHead label="Tool call" variant="accent" />
            <p className="chat__prose">
              I ran the <span className="mono">total_reported_income</span> tool on your T4. The
              figure is computed from the document, not written by the model.
            </p>

            <div className="tool-card">
              <div className="tool-card__head">
                <span className="mono tool-card__name">Tool call · total_reported_income</span>
                <span className="tool-card__head-right">
                  <span className="mono">ti_0192e4b1</span>
                  <StatusPill variant="success">Logged</StatusPill>
                </span>
              </div>

              <dl className="tool-card__facts">
                <div>
                  <dt>Input</dt>
                  <dd>
                    <span className="mono">document_id = doc_7f3a21c9</span> (only input)
                  </dd>
                </div>
                <div>
                  <dt>Result</dt>
                  <dd className="mono tool-card__result">94,500.00 CAD</dd>
                </div>
                <div>
                  <dt>Source</dt>
                  <dd>2024_T4_AcmeCorp.pdf · p.1 · Employment income</dd>
                </div>
                <div>
                  <dt>Logged at</dt>
                  <dd className="mono">Sep 22, 14:21:58 UTC</dd>
                </div>
              </dl>

              <div className="tool-card__section">
                <div className="tool-card__section-head">
                  <span className="mono">Proposed journal entry</span>
                  <StatusPill variant="success">Balanced</StatusPill>
                </div>
                <table className="tool-card__table">
                  <thead>
                    <tr>
                      <th>Account</th>
                      <th className="num">Debit</th>
                      <th className="num">Credit</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Employment Income Receivable</td>
                      <td className="num mono">94,500.00</td>
                      <td className="num mono">—</td>
                    </tr>
                    <tr>
                      <td>Reported Income</td>
                      <td className="num mono">—</td>
                      <td className="num mono">94,500.00</td>
                    </tr>
                  </tbody>
                  <tfoot>
                    <tr>
                      <td>Total</td>
                      <td className="num mono">94,500.00</td>
                      <td className="num mono">94,500.00</td>
                    </tr>
                  </tfoot>
                </table>
                <div className="tool-card__key">
                  <span className="tool-card__key-label">Idempotency key</span>
                  <span className="mono">doc_7f3a21c9:ti_0192e4b1</span>
                </div>
              </div>

              <div className="tool-card__actions">
                {posted ? (
                  <span className="tool-card__posted">
                    <CheckIcon size={14} /> Posted as <span className="mono">pst_98f102a4</span>
                    <Link to="/ledger">View in Ledger →</Link>
                  </span>
                ) : (
                  <>
                    <button type="button" className="btn btn-primary" onClick={() => setPosted(true)}>
                      Post to ledger
                    </button>
                    <span className="tool-card__help">
                      Goes through the same idempotent POST /postings as every other entry. Posting
                      twice has no effect.
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Turn 3 — no answer: nothing cleared the relevance threshold */}
          <div className="chat__turn chat__turn--user">
            <div className="chat__bubble--user">What was my charitable donation amount in 2024?</div>
          </div>

          <div className="chat__turn chat__turn--assistant">
            <AssistantHead label="No answer" variant="warning" />
            <p className="chat__prose">
              I couldn't find this in your indexed documents, so I won't guess.
            </p>
            <div className="chat__no-answer-meta mono">
              Best match 0.41 · below relevance threshold 0.70
            </div>
            <div className="chat__no-answer-nudge">
              Have a donation receipt? <Link to="/documents">Upload in Documents →</Link>
            </div>
          </div>
        </div>
      </div>

      <div className="chat__composer">
        <div className="chat__composer-inner">
          <div className="chat__composer-bar">
            <input
              type="text"
              className="chat__composer-input"
              placeholder="Ask about your indexed documents…"
              aria-label="Ask about your indexed documents"
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
            />
            <button type="button" className="chat__composer-send" aria-label="Send message">
              <ArrowUpIcon size={16} />
            </button>
          </div>
          <div className="chat__composer-foot">
            Answers come only from your indexed documents and always cite their source. If nothing
            relevant is found, the assistant says so.
          </div>
        </div>
      </div>
    </div>
  );
}
