import { useEffect } from 'react';
import { CheckIcon, LockIcon, SparkleIcon, PaperclipIcon, LedgerIcon, DocumentsIcon } from '../components/Icons';
import './Landing.css';

type LandingProps = {
  onEnterApp: () => void;
};

export function Landing({ onEnterApp }: LandingProps) {
  useEffect(() => {
    const targets = document.querySelectorAll('.reveal');
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            io.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.15 },
    );
    targets.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  return (
    <div className="landing">
      <header className="landing__nav">
        <div className="landing__brand">
          <span className="landing__brand-mark" aria-hidden="true" />
          Ledger Assistant
        </div>
        <nav className="landing__nav-links">
          <a href="#product">Product</a>
          <a href="#how-it-works">How it works</a>
          <a href="#security">Security</a>
          <a href="#docs">Docs</a>
        </nav>
        <button type="button" className="btn btn-primary" onClick={onEnterApp}>
          See it in action
        </button>
      </header>

      <section className="landing__hero">
        <span className="landing__eyebrow mono">
          <span className="landing__eyebrow-dot" /> DOCUMENT-GROUNDED LEDGER ASSISTANT
        </span>
        <h1 className="landing__headline">
          Ask your documents. Get a cited answer. Post it to the ledger.
        </h1>
        <p className="landing__subhead">
          Ledger Assistant retrieves the relevant passage from your uploaded tax slips, cites
          exact page and location, and prepares a balanced journal entry for your review.
        </p>
        <div className="landing__hero-actions">
          <button type="button" className="btn btn-primary" onClick={onEnterApp}>
            See it in action
          </button>
          <span className="landing__hero-note mono">
            <CheckIcon size={14} /> DOUBLE-ENTRY BALANCE ENFORCED
          </span>
        </div>

        <div className="landing__mockup">
          <div className="landing__mockup-bar">
            <span className="mono">SESSION ID: #LA-9042 · TAX YEAR 2024</span>
            <span className="mono landing__mockup-status">STATUS: ACTIVE CONTEXT</span>
          </div>

          <div className="landing__mockup-user">
            What was our total state withholding reported on the 2024 Form 941, and does it
            match Schedule B line 12?
          </div>
          <div className="landing__mockup-meta mono">10:41 AM · Verified User (Controller)</div>

          <div className="landing__mockup-assistant">
            <div className="landing__mockup-assistant-name">
              <SparkleIcon size={14} className="landing__sparkle" /> Ledger Assistant · 10:41:04 AM
            </div>
            <p>
              Total state tax withholding across Schedule B matches the Form 941 line 2 summary
              at <strong>$148,290.40</strong>. There is an unallocated difference of $0.00
              against payroll journal #JE-8821.
            </p>

            <div className="landing__citation">
              <div>
                <div className="landing__citation-name">
                  <PaperclipIcon size={12} /> US_Form_941_Q4_2024_Final.pdf
                </div>
                <div className="landing__citation-loc mono">
                  Page 2, Box 2 &amp; Schedule B Line 12 · Coordinate (x:420, y:692)
                </div>
              </div>
              <span className="status-pill status-pill--success mono">CONFIDENCE 99.8%</span>
            </div>

            <div className="landing__ledger-card">
              <div className="landing__ledger-card-head mono">
                <span>PROPOSED BALANCED GENERAL LEDGER ENTRY</span>
                <span>TOLERANCE: ±$0.00</span>
              </div>
              <div className="landing__ledger-row mono">
                <span>DEBIT&nbsp;&nbsp;2200 · State Withholding Payable</span>
                <span>$148,290.40</span>
              </div>
              <div className="landing__ledger-row mono">
                <span>CREDIT&nbsp;1010 · Operating Cash Account</span>
                <span>$148,290.40</span>
              </div>
              <div className="landing__ledger-card-foot">
                <span className="mono landing__pending">Pending reviewer authorization</span>
                <button type="button" className="btn btn-primary landing__confirm-btn" disabled>
                  <LockIcon size={12} /> Confirm &amp; Post Entry
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="landing__showcase" id="product">
        <div className="landing__showcase-header reveal">
          <span className="landing__eyebrow-label mono">DESIGNED FOR REVIEW, NOT AUTOMATION</span>
          <h2 className="landing__section-title">Designed for finance operations. Verified before commit.</h2>
        </div>

        <div className="landing__showcase-grid reveal">
          <div className="landing__showcase-text">
            <div className="landing__feature-icon" aria-hidden="true">
              <DocumentsIcon size={16} />
            </div>
            <h2>Cited answers from source slips</h2>
            <p>
              Every extraction links directly to the underlying PDF page, bounding-box coordinates, and field confidence score for immediate visual audit.
            </p>
          </div>
          <div className="landing__showcase-visual">
            <div className="landing__ui-card" style={{ padding: '16px' }}>
               <div className="landing__citation" style={{ marginBottom: 0 }}>
                  <div>
                    <div className="landing__citation-name">
                      <PaperclipIcon size={12} /> T4_Slip14.pdf
                    </div>
                    <div className="landing__citation-loc mono">
                      Page 1, Coordinate (x:142, y:308)
                    </div>
                  </div>
                  <span className="status-pill status-pill--success mono">99.8%</span>
               </div>
            </div>
          </div>
        </div>

        <div className="landing__showcase-grid landing__showcase-grid--reverse reveal" id="security">
          <div className="landing__showcase-text">
            <div className="landing__feature-icon" aria-hidden="true">
              <LockIcon size={16} />
            </div>
            <h2>Explicit human confirmation</h2>
            <p>
              No automated write actions occur without an authenticated reviewer confirming a balanced debit and credit allocation first.
            </p>
          </div>
          <div className="landing__showcase-visual">
            <div className="landing__ui-card">
              <div className="landing__ui-card-header mono">
                <span>ACTION: POST_JOURNAL_ENTRY</span>
                <span className="landing__ui-badge landing__ui-badge--warning">AWAITING CONFIRMATION</span>
              </div>
              <div className="landing__ui-list">
                <div className="landing__ui-item">
                  <div className="landing__ui-item-left">
                    <span className="landing__ui-title">Review proposed entry</span>
                    <span className="landing__ui-sub mono">USER: CONTROLLER</span>
                  </div>
                  <div className="landing__ui-item-right mono">
                    PENDING
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="landing__showcase-grid reveal">
          <div className="landing__showcase-text">
            <div className="landing__feature-icon" aria-hidden="true">
              <CheckIcon size={16} />
            </div>
            <h2>Mathematical balance guarantees</h2>
            <p>
              A deferred constraint trigger enforces strict debits-equal-credits parity within the same transaction as every posting insert.
            </p>
          </div>
          <div className="landing__showcase-visual landing__showcase-visual--code mono">
            <div className="landing__code-bar">
              <span className="landing__code-dot"></span>
              <span className="landing__code-dot"></span>
              <span className="landing__code-dot"></span>
            </div>
            <pre>
              <code>
<span className="landing__code-kw">CHECK</span>: sum(DR) - sum(CR) = $0.00<br/>
<br/>
<span className="landing__code-comment">-- Enforced within the same transaction</span><br/>
<span className="landing__code-comment">-- as every posting insert.</span>
              </code>
            </pre>
          </div>
        </div>
      </section>

      <section className="landing__infrastructure reveal" id="how-it-works">
        <div className="landing__infra-content">
          <span className="landing__eyebrow-label mono">UNDER THE HOOD</span>
          <h2 className="landing__section-title">How it works</h2>
          <div className="landing__infra-grid">
            <div className="landing__infra-card">
              <div className="landing__infra-icon-badge">
                <DocumentsIcon size={20} className="landing__infra-icon" />
              </div>
              <h3>Supported documents</h3>
              <p>W-2, 1099-NEC, 1099-MISC, T4, T5, Form 941, Schedule C, 1065 K-1, and custom institutional financial schedules.</p>
            </div>
            <div className="landing__infra-card">
              <div className="landing__infra-icon-badge">
                <SparkleIcon size={20} className="landing__infra-icon" />
              </div>
              <h3>Retrieval &amp; generation</h3>
              <p>AWS Textract OCR extraction feeds a pgvector similarity index in Postgres. Every answer is generated through a LiteLLM-routed model call, grounded in the retrieved passages — never open free-text recall.</p>
            </div>
            <div className="landing__infra-card">
              <div className="landing__infra-icon-badge">
                <LedgerIcon size={20} className="landing__infra-icon" />
              </div>
              <h3>Double-entry ledger core</h3>
              <p>Every posting is enforced by a deferred balance-invariant constraint trigger — debits equal credits within the same transaction, or it rolls back. Idempotency keys prevent duplicate writes on retry.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="landing__cta-section" id="docs">
        <div className="landing__cta-layout">
          <div className="landing__cta-content">
            <h2 className="landing__cta-title">Ready to secure your ledger ops?</h2>
            <ul className="landing__cta-bullets">
              <li><CheckIcon size={14} className="landing__cta-check" /> Cites the exact source page for every figure</li>
              <li><CheckIcon size={14} className="landing__cta-check" /> Never posts to the ledger without human confirmation</li>
              <li><CheckIcon size={14} className="landing__cta-check" /> Posts to a real double-entry ledger, not a mock</li>
            </ul>
            <div className="landing__cta-actions">
              <button type="button" className="btn btn-primary btn-lg" onClick={onEnterApp}>
                See it in action
              </button>
            </div>
          </div>
          <div className="landing__cta-visual">
            <div className="landing__ui-card landing__cta-mockup">
              <div className="landing__ledger-card-head mono" style={{ borderBottom: '1px solid var(--color-border)' }}>
                <span>PROPOSED BALANCED GENERAL LEDGER ENTRY</span>
              </div>
              <div className="landing__ledger-row mono">
                <span>DEBIT&nbsp;&nbsp;2200 · State Withholding</span>
                <span>$148,290.40</span>
              </div>
              <div className="landing__ledger-row mono">
                <span>CREDIT&nbsp;1010 · Operating Cash</span>
                <span>$148,290.40</span>
              </div>
              <div className="landing__ledger-card-foot mono" style={{ borderTop: '1px solid var(--color-border)', color: 'var(--color-success)' }}>
                <span>Confirmed &amp; Posted ✓</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <footer className="landing__footer">
        <div className="landing__brand">
          <span className="landing__brand-mark" aria-hidden="true" />
          Ledger Assistant
        </div>
        <span className="mono landing__footer-copy">
          © 2026 Ledger Assistant. Document-grounded ledger review, built for finance operations.
        </span>
      </footer>
    </div>
  );
}
