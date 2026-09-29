import { Link } from 'react-router';
import { BrandMark } from '../components/BrandMark';
import { CheckIcon, LockIcon, RefreshIcon, SparkleIcon } from '../components/Icons';
import { HeroFlow } from '../components/HeroFlow';
import './Landing.css';

const STEPS = [
  {
    title: 'Read the agreement',
    body: 'Upload an investment advisory agreement as a PDF. It is parsed on your machine, names, emails, phone and account numbers are replaced with tokens, and the fee schedule is extracted together with the clause it came from.',
  },
  {
    title: 'Reconcile it with billing',
    body: 'Ask about any contract in plain language. Answers cite the clause and page, and billing reconciliation is computed in code from your billing schedule. The model never does the arithmetic.',
  },
  {
    title: 'Approve the correction',
    body: 'When the contract and billing disagree, the assistant proposes a balanced journal entry, logged in the AI decision audit trail with its model, inputs and citations. It reaches the ledger only after a person approves it, and it posts exactly once.',
  },
];

const GUARANTEES = [
  'Tools take document IDs, and code computes every fee. The model never supplies an amount.',
  'Every number in an answer traces to the page and clause that state it, never asserted without a citation.',
  "A field the extractor couldn't confirm sits in the extraction anomaly queue until a person resolves it; the assistant won't use it.",
  'The ledger is append-only. A mistake is undone with a reversal, never an edit.',
];

export function Landing() {
  return (
    <div className="landing">
      <header className="landing__nav">
        <div className="landing__brand">
          <BrandMark size={24} />
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
          Ledger Assistant reads your investment advisory agreements, answers questions with the clause cited, and
          reconciles each fee schedule against what billing actually charges. When they disagree, it proposes the exact
          correcting entry, and it posts only after a person approves it, logged the moment they do.
        </p>
        <div className="landing__hero-actions">
          <Link to="/dashboard" className="btn btn-primary">
            Open the demo
          </Link>
          <Link to="/chat" className="btn landing__btn-ghost">
            Ask a contract
          </Link>
        </div>

        <HeroFlow />
      </section>

      <section className="landing__pillars" aria-label="What this demonstrates at three levels">
        <div className="landing__pillars-inner">
          <div className="landing__pillar landing__pillar--ops">
            <span className="landing__pillar-eyebrow">Rule engine</span>
            <div className="landing__pillar-title">
              <RefreshIcon size={16} className="landing__pillar-icon" />
              Ops
            </div>
            <p className="landing__pillar-desc">
              Billing reconciliation: the gap between contract and billing,{' '}
              <code className="mono landing__pillar-code">computed in code</code>, never by the model.
            </p>
          </div>
          <div className="landing__pillar landing__pillar--governance">
            <span className="landing__pillar-eyebrow">Chain of custody</span>
            <div className="landing__pillar-title">
              <LockIcon size={16} className="landing__pillar-icon" />
              Governance
            </div>
            <p className="landing__pillar-desc">
              Every AI tool call is <code className="mono landing__pillar-code">logged</code> with its model, inputs
              and decision, before anything reaches the ledger.
            </p>
          </div>
          <div className="landing__pillar landing__pillar--audit">
            <span className="landing__pillar-eyebrow">Cryptographic audit</span>
            <div className="landing__pillar-title">
              <CheckIcon size={16} className="landing__pillar-icon" />
              Audit
            </div>
            <p className="landing__pillar-desc">
              The GL export is byte-identical on regeneration and verified by its{' '}
              <code className="mono landing__pillar-code">SHA-256</code> hash.
            </p>
          </div>
        </div>
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
          <BrandMark size={24} />
          Ledger Assistant
        </div>
        <span className="landing__footer-copy">A working demo: fee-contract reconciliation and a governed AI, on a double-entry ledger.</span>
        <Link to="/dashboard">Open the demo →</Link>
      </footer>
    </div>
  );
}
