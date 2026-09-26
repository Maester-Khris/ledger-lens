import { Link } from 'react-router';
import { CheckIcon, LockIcon, SparkleIcon } from '../components/Icons';
import './Landing.css';

const STEPS = [
  {
    title: 'Read the agreement',
    body: 'Upload an investment advisory agreement as a PDF. It is parsed on your machine, names, emails, phone and account numbers are replaced with tokens, and the fee schedule is extracted together with the clause it came from.',
  },
  {
    title: 'Compare it with billing',
    body: 'Ask about any contract in plain language. Answers cite the clause and page, and the fee comparison is computed in code from your billing schedule — the model never does the arithmetic.',
  },
  {
    title: 'Approve the correction',
    body: 'When the contract and billing disagree, the assistant proposes a balanced journal entry. It reaches the ledger only after a person approves it, and it posts exactly once.',
  },
];

const GUARANTEES = [
  'Tools take document IDs, and code computes every fee. The model never supplies an amount.',
  'Every number in an answer is checked against the passage it cites.',
  'Fields the extractor could not ground wait for a person before the assistant can use them.',
  'The ledger is append-only. A mistake is undone with a reversal, never an edit.',
];

export function Landing() {
  return (
    <div className="landing">
      <header className="landing__nav">
        <div className="landing__brand">
          <span className="landing__brand-mark" aria-hidden="true" />
          Ledger Assistant
        </div>
        <nav className="landing__nav-links" aria-label="Page sections">
          <a href="#how-it-works">How it works</a>
          <a href="#guarantees">Guarantees</a>
        </nav>
        <Link to="/dashboard" className="btn btn-primary">
          Open the demo
        </Link>
      </header>

      <section className="landing__hero">
        <h1 className="landing__headline">Bill what the contract says.</h1>
        <p className="landing__subhead">
          Ledger Assistant reads your investment advisory agreements, answers questions with the clause cited, and checks
          each fee schedule against what billing actually charges. When they differ, it proposes the correction — and a
          person approves it before anything posts.
        </p>
        <div className="landing__hero-actions">
          <Link to="/dashboard" className="btn btn-primary">
            Open the demo
          </Link>
          <Link to="/chat" className="btn landing__btn-ghost">
            Ask a contract
          </Link>
        </div>

        <figure className="landing__compare" aria-label="Example: a contract compared with billing">
          <figcaption className="landing__compare-caption mono">Example comparison</figcaption>
          <div className="landing__compare-grid">
            <div className="landing__compare-col">
              <span className="landing__compare-source mono">Agreement · §3 Fees · p.2</span>
              <p className="landing__compare-quote">
                “1.00% per annum on the first $1,000,000 of assets under management”
              </p>
            </div>
            <div className="landing__compare-col">
              <span className="landing__compare-source mono">Billing schedule · household</span>
              <p className="landing__compare-billed mono">0.85% on the first $1,000,000</p>
            </div>
          </div>
          <div className="landing__compare-gap">
            <span className="mono landing__gap-amount">Annual gap 1,500.00 CAD</span>
            <span className="landing__gap-status">
              <LockIcon size={12} /> Correction proposed · awaiting approval
            </span>
          </div>
        </figure>
      </section>

      <section className="landing__section" id="how-it-works">
        <h2 className="landing__section-title">How it works</h2>
        <ol className="landing__steps">
          {STEPS.map((step, index) => (
            <li key={step.title} className="landing__step">
              <span className="landing__step-number mono">{index + 1}</span>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="landing__section landing__section--split" id="guarantees">
        <div>
          <h2 className="landing__section-title">What it will not do</h2>
          <p className="landing__section-lede">
            The assistant is built for review, not autopilot. These rules are enforced in code and in the database, not
            in the prompt.
          </p>
        </div>
        <ul className="landing__guarantees">
          {GUARANTEES.map((line) => (
            <li key={line}>
              <CheckIcon size={14} className="landing__check" /> {line}
            </li>
          ))}
        </ul>
      </section>

      <section className="landing__stack">
        <p className="mono">
          <SparkleIcon size={12} /> Docling and Presidio run locally · Postgres full-text + Pinecone retrieval · OpenAI via
          LangGraph · double-entry ledger on PostgreSQL
        </p>
      </section>

      <footer className="landing__footer">
        <div className="landing__brand landing__brand--dark">
          <span className="landing__brand-mark" aria-hidden="true" />
          Ledger Assistant
        </div>
        <span className="landing__footer-copy">A working demo: fee-contract review on a double-entry ledger.</span>
        <Link to="/dashboard">Open the demo →</Link>
      </footer>
    </div>
  );
}
