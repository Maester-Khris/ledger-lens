import { useEffect, useState } from 'react';
import { DocumentsIcon, LedgerIcon, RefreshIcon } from './Icons';
import { nextFlowPhase } from '../lib/flowPhase';
import { useCountUp } from '../lib/useCountUp';
import './HeroFlow.css';

// ponytail: a fixed 7-phase timeline for this one diagram, not a general animation engine.
// Phases: 0 source lit, 1 dot travels left, 2 contract rate counts up, 3 exchange icon pulses,
// 4 billing rate counts up, 5 dot travels right, 6 ledger lit + posted amount counts up.
// It plays once and holds on phase 6, so the diagram never shows zeros after the first few seconds.
// One duration per phase that is followed by another; the last phase has none because it never ends.
const PHASE_DURATIONS_MS = [600, 600, 900, 500, 900, 600];
const PHASE_COUNT = PHASE_DURATIONS_MS.length + 1;
const LAST_PHASE = PHASE_COUNT - 1;
const COUNT_UP_MS = 900;

const CONTRACT_RATE = 0.85;
const BILLING_RATE = 0.8;
const POSTED_AMOUNT = 400;
// Shown in a value slot before its count-up starts, so the diagram never reads "0.00%".
const PENDING = '· · ·';

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function useFlowPhase(reduced: boolean): number {
  const [phase, setPhase] = useState(0);
  useEffect(() => {
    if (reduced || phase >= LAST_PHASE) return;
    const timer = setTimeout(() => setPhase((p) => nextFlowPhase(p, PHASE_COUNT)), PHASE_DURATIONS_MS[phase]);
    return () => clearTimeout(timer);
  }, [phase, reduced]);
  return phase;
}

export function HeroFlow() {
  const [reduced] = useState(prefersReducedMotion);
  const phase = useFlowPhase(reduced);

  const sourceActive = !reduced && phase === 0;
  const dotLeft = !reduced && phase === 1;
  const contractCounting = !reduced && phase >= 2;
  const exchangeActive = !reduced && phase === 3;
  const billingCounting = !reduced && phase >= 4;
  const dotRight = !reduced && phase === 5;
  const ledgerActive = !reduced && phase === LAST_PHASE;

  const contractRate = useCountUp(CONTRACT_RATE, contractCounting, COUNT_UP_MS, reduced);
  const billingRate = useCountUp(BILLING_RATE, billingCounting, COUNT_UP_MS, reduced);
  const posted = useCountUp(POSTED_AMOUNT, ledgerActive, COUNT_UP_MS, reduced);

  const showContract = reduced || contractCounting;
  const showBilling = reduced || billingCounting;
  const showPosted = reduced || ledgerActive;

  return (
    <div className="hero-flow" aria-hidden="true">
      <div className="hero-flow__row">
        <div className="hero-flow__node">
          <span className="hero-flow__label">Agreement</span>
          <div className={`hero-flow__card${sourceActive ? ' hero-flow__card--active' : ''}`}>
            <DocumentsIcon size={20} />
            <span className="hero-flow__value mono">§3 Fees · p.1</span>
          </div>
        </div>

        <div className="hero-flow__connector">{dotLeft && <span className="hero-flow__dot" />}</div>

        <div className="hero-flow__hub">
          <span className="hero-flow__label">Reconciliation</span>
          <div className="hero-flow__hub-inner">
            <div className="hero-flow__card hero-flow__card--inner">
              <span className="hero-flow__inner-label">Contract states</span>
              <span className="hero-flow__value mono">{showContract ? `${contractRate.toFixed(2)}%` : PENDING}</span>
            </div>
            <div className={`hero-flow__exchange${exchangeActive ? ' hero-flow__exchange--active' : ''}`}>
              <RefreshIcon size={16} />
            </div>
            <div className="hero-flow__card hero-flow__card--inner">
              <span className="hero-flow__inner-label">Billing charges</span>
              <span className="hero-flow__value mono">{showBilling ? `${billingRate.toFixed(2)}%` : PENDING}</span>
            </div>
          </div>
        </div>

        <div className="hero-flow__connector">{dotRight && <span className="hero-flow__dot" />}</div>

        <div className="hero-flow__node">
          <span className="hero-flow__label">Ledger</span>
          <div className={`hero-flow__card${ledgerActive ? ' hero-flow__card--active' : ''}`}>
            <LedgerIcon size={20} />
            <span className="hero-flow__value mono">{showPosted ? `$${posted.toFixed(2)}` : PENDING}</span>
          </div>
        </div>
      </div>

      <ul className="hero-flow__chips">
        <li>PII tokenized locally</li>
        <li>Contract ↔ billing, compared on request</li>
        <li>Human approval required</li>
        <li>Full audit trail</li>
      </ul>
    </div>
  );
}
