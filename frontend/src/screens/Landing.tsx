import { Link } from 'react-router';
import { BrandMark } from '../components/BrandMark';
import { CheckIcon, LockIcon, RefreshIcon, SparkleIcon } from '../components/Icons';
import { HeroFlow } from '../components/HeroFlow';
import './Landing.css';

const REPO_URL = 'https://github.com/Maester-Khris/ledger-lens';
// The reports are on preview and not yet on main; switch to main after the next release.
const REPORTS_URL = `${REPO_URL}/tree/preview/backend/reports`;

const STEPS = [
  {
    title: 'Read the agreement',
    stage: 'Ingestion',
    body: 'Upload an investment advisory agreement as a PDF. It is parsed and tokenized before anything reaches a model: names, emails, phone and account numbers are replaced with tokens, and the fee schedule is extracted together with the clause it came from.',
  },
  {
    title: 'Reconcile it with billing',
    stage: 'Comparison',
    body: 'Ask about any contract in plain language. Answers cite the clause and page, and billing reconciliation is computed in code from your billing schedule. The model never does the arithmetic.',
  },
  {
    title: 'Approve the correction',
    stage: 'Approval',
    body: 'When the contract and billing disagree, the assistant proposes a balanced journal entry, logged in the AI decision audit trail with its model, inputs and citations. It reaches the ledger only after a person approves it, and it posts exactly once.',
  },
];

const GUARANTEES = [
  { label: 'Computation invariant', text: 'Tools take document IDs, and code computes every fee. The model never supplies an amount.' },
  { label: 'Citation check', text: 'Every number in an answer traces to the page and clause that state it, never asserted without a citation.' },
  { label: 'Extraction review', text: "A field the extractor couldn't confirm sits in the extraction anomaly queue until a person resolves it; the assistant won't use it." },
  { label: 'Ledger immutability', text: 'The ledger is append-only. A mistake is undone with a reversal, never an edit.' },
];

// Every figure here is copied from a report in the repository; the source column names it.
// tone: 'ok' is a clean result, 'warn' one that is not perfect on every run.
const PROOF: { claim: string; measured: string; tone: 'ok' | 'warn'; source: string; date: string }[] = [
  {
    claim: 'No duplicate postings under load',
    measured: '0 of 500 concurrent requests',
    tone: 'ok',
    source: 'reports/concurrency.json',
    date: '2026-09-23',
  },
  {
    claim: 'Answerable questions answered with the right numbers and a citation',
    measured: '27 to 28 of 28, across three runs',
    tone: 'warn',
    source: 'reports/eval-5bfdd62942f4*.json',
    date: '2026-10-02',
  },
  {
    claim: 'Unanswerable questions refused or sent back for clarification',
    measured: '21 of 21, across three runs',
    tone: 'ok',
    source: 'reports/eval-5bfdd62942f4*.json',
    date: '2026-10-02',
  },
];

const DATA_HANDLING = [
  'Names, emails, phone and account numbers are tokenized before any text reaches a model.',
  'Parsing and tokenization run locally, with Docling and Presidio.',
  'Search vectors are stored in Pinecone (AWS us-east-1).',
  'Answers and extraction use OpenAI GPT-4.1, pinned to a dated snapshot.',
  'Search embeddings use OpenAI text-embedding-3-small.',
];

const DEMO_LIMITS = [
  'Agreements are synthetic or public EDGAR filings. There is no client data.',
  'Guests are identified for attribution, not authenticated.',
  'In the public demo, approvals are checked by the ledger but not recorded.',
  'One tenant.',
  'A comparison runs when you ask for it, against the billing schedule in effect, not against invoices.',
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
          <a href="#guarantees">Guarantees</a>
          <a href="#proof">Proof</a>
          <a href="#how-it-works">How it works</a>
        </nav>
        <Link to="/dashboard" className="btn btn-primary">
          Open the demo
        </Link>
      </header>

      <section className="landing__hero">
        <p className="landing__eyebrow mono">For billing operations and compliance teams at Canadian portfolio managers</p>
        <h1 className="landing__headline">Bill what the contract says.</h1>
        <p className="landing__subhead">
          Ledger Assistant reads your investment advisory agreements, answers questions with the clause cited, and
          checks each fee schedule against what your billing schedule would charge. When they disagree, it proposes a
          correcting entry that posts only after a person approves it.
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
            <span className="landing__pillar-eyebrow">Decision log</span>
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
            <span className="landing__pillar-eyebrow">Reproducible export</span>
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

      <section className="landing__section" id="guarantees">
        <div className="landing__section-head">
          <div>
            <p className="landing__kicker mono">Deterministic constraints</p>
            <h2 className="landing__section-title">What it will not do</h2>
          </div>
          <p className="landing__section-lede">
            The assistant is built for review, not autopilot. These rules are enforced in code and in the database, not
            in the prompt.
          </p>
        </div>
        <ul className="landing__guarantees">
          {GUARANTEES.map((item) => (
            <li key={item.label} className="landing__card">
              <span className="landing__check"><CheckIcon size={14} /></span>
              <div>
                <span className="landing__guarantee-label mono">{item.label}</span>
                <p>{item.text}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="landing__section" id="proof">
        <div className="landing__section-head">
          <div>
            <p className="landing__kicker mono">Load test and eval results</p>
            <h2 className="landing__section-title">Measured, with the source</h2>
            <p className="landing__section-lede">
              Each result below is copied from a report in the repository, so you can check it.
            </p>
          </div>
        </div>
        <div className="landing__card landing__card--flush">
        <table className="landing__proof">
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Measured</th>
              <th scope="col">Source</th>
              <th scope="col">Date</th>
            </tr>
          </thead>
          <tbody>
            {PROOF.map((row) => (
              <tr key={row.claim}>
                <th scope="row">{row.claim}</th>
                <td className="landing__proof-measured mono">
                  <span className={`landing__pill landing__pill--${row.tone}`}>{row.measured}</span>
                </td>
                <td className="landing__proof-source mono">{row.source}</td>
                <td className="landing__proof-source mono">{row.date}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </section>

      <section className="landing__section" id="how-it-works">
        <div className="landing__section-head">
          <div>
            <p className="landing__kicker mono">Workflow</p>
            <h2 className="landing__section-title">How it works</h2>
          </div>
        </div>
        <ol className="landing__steps">
          {STEPS.map((step, index) => (
            <li key={step.title} className="landing__step landing__card">
              <div className="landing__step-top">
                <span className="landing__step-number mono">{index + 1}</span>
                <span className="landing__step-stage mono">Stage: {step.stage}</span>
              </div>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="landing__section" id="limits">
        <div className="landing__section-head">
          <div>
            <p className="landing__kicker mono">Data handling and limits</p>
            <h2 className="landing__section-title">Before you rely on it</h2>
          </div>
        </div>
        <div className="landing__card">
        <div className="landing__trust">
          <div>
            <h3 className="landing__trust-title">How your data is handled</h3>
            <ul className="landing__facts">
              {DATA_HANDLING.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="landing__trust-title landing__trust-title--muted">Limits of this demo</h3>
            <ul className="landing__facts">
              {DEMO_LIMITS.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        </div>
        <p className="landing__note">
          The decision log records the tool, model, prompt version, inputs and approver for every AI action, in line
          with the transparency and accountability themes of CSA Staff Notice 11-348 on AI in capital markets. This
          demo has not been assessed for compliance with any regulation.
        </p>
        </div>
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
        <div className="landing__footer-links">
          <a href={REPO_URL} target="_blank" rel="noreferrer">Source on GitHub</a>
          <a href={REPORTS_URL} target="_blank" rel="noreferrer">Evaluation reports</a>
          <Link to="/dashboard">Open the demo →</Link>
        </div>
      </footer>
    </div>
  );
}
