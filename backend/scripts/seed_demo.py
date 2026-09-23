"""Seed ledger_dev with the demo tenant's book: run `./scripts/db_up.sh` first, then
`.venv/bin/python scripts/seed_demo.py` from backend/. Safe to run twice."""
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects.postgresql import Range  # noqa: E402

from app.billing.models import (  # noqa: E402
    AccountValuation, Client, ClientAccount, FeeSchedule, FeeScheduleTier,
    FeeScheduleVersion, Household, HouseholdFeeAssignment,
)
from app.billing.types import FeeMethod  # noqa: E402
from app.ledger.db import SessionLocal  # noqa: E402
from app.ledger.models import Account  # noqa: E402
from app.ledger.types import DEMO_TENANT_ID, NormalBalance  # noqa: E402

T = DEMO_TENANT_ID
ID = {name: uuid.uuid5(uuid.NAMESPACE_URL, f"ledger-lens-demo/{name}") for name in (
    "revenue", "cash_marie", "cash_luc", "cash_ada", "receivable", "reported_income",
    "hh_tremblay", "hh_okafor", "client_marie", "client_luc", "client_ada", "schedule",
)}


def main() -> None:
    with SessionLocal() as session:
        if session.get(Household, ID["hh_tremblay"]) is not None:
            print("Demo data already present; nothing to do.")
            return
        session.add_all([
            Account(id=ID["revenue"], tenant_id=T, name="Advisory Fee Revenue", currency="CAD", normal_balance=NormalBalance.credit, gl_code="4000"),
            Account(id=ID["cash_marie"], tenant_id=T, name="Client cash - Tremblay, Marie", currency="CAD", normal_balance=NormalBalance.credit, gl_code="2100"),
            Account(id=ID["cash_luc"], tenant_id=T, name="Client cash - Tremblay, Luc", currency="CAD", normal_balance=NormalBalance.credit, gl_code="2100"),
            Account(id=ID["cash_ada"], tenant_id=T, name="Client cash - Okafor, Ada", currency="CAD", normal_balance=NormalBalance.credit, gl_code="2100"),
            Account(id=ID["receivable"], tenant_id=T, name="Employment Income Receivable", currency="CAD", normal_balance=NormalBalance.debit, gl_code="1200"),
            Account(id=ID["reported_income"], tenant_id=T, name="Reported Income", currency="CAD", normal_balance=NormalBalance.credit, gl_code="4100"),
            Household(id=ID["hh_tremblay"], tenant_id=T, name="Tremblay"),
            Household(id=ID["hh_okafor"], tenant_id=T, name="Okafor"),
        ])
        session.flush()
        session.add_all([
            Client(id=ID["client_marie"], tenant_id=T, household_id=ID["hh_tremblay"], name="Marie Tremblay"),
            Client(id=ID["client_luc"], tenant_id=T, household_id=ID["hh_tremblay"], name="Luc Tremblay"),
            Client(id=ID["client_ada"], tenant_id=T, household_id=ID["hh_okafor"], name="Ada Okafor"),
            FeeSchedule(id=ID["schedule"], tenant_id=T, name="Standard wealth", revenue_account_id=ID["revenue"]),
        ])
        session.flush()
        session.add_all([
            ClientAccount(account_id=ID["cash_marie"], client_id=ID["client_marie"], linked_on=date(2026, 1, 1)),
            ClientAccount(account_id=ID["cash_luc"], client_id=ID["client_luc"], linked_on=date(2026, 8, 1)),
            ClientAccount(account_id=ID["cash_ada"], client_id=ID["client_ada"], linked_on=date(2026, 1, 1)),
            AccountValuation(account_id=ID["cash_marie"], as_of=date(2026, 9, 30), market_value_minor=120_000_000, source="seed"),
            AccountValuation(account_id=ID["cash_luc"], as_of=date(2026, 9, 30), market_value_minor=60_000_000, source="seed"),
            AccountValuation(account_id=ID["cash_ada"], as_of=date(2026, 9, 30), market_value_minor=45_000_000, source="seed"),
            FeeScheduleVersion(schedule_id=ID["schedule"], version=1, method=FeeMethod.graduated,
                               valid_during=Range(date(2026, 1, 1), date(2026, 6, 30), bounds="[]")),
            FeeScheduleVersion(schedule_id=ID["schedule"], version=2, method=FeeMethod.graduated,
                               valid_during=Range(date(2026, 7, 1), None, bounds="[)")),
        ])
        session.flush()
        session.add_all([
            FeeScheduleTier(schedule_id=ID["schedule"], version=1, tier_no=1, up_to_minor=None, rate_bps=Decimal("150")),
            FeeScheduleTier(schedule_id=ID["schedule"], version=2, tier_no=1, up_to_minor=100_000_000, rate_bps=Decimal("100")),
            FeeScheduleTier(schedule_id=ID["schedule"], version=2, tier_no=2, up_to_minor=250_000_000, rate_bps=Decimal("80")),
            FeeScheduleTier(schedule_id=ID["schedule"], version=2, tier_no=3, up_to_minor=None, rate_bps=Decimal("65")),
            HouseholdFeeAssignment(household_id=ID["hh_tremblay"], schedule_id=ID["schedule"], valid_during=Range(date(2026, 1, 1), None, bounds="[)")),
            HouseholdFeeAssignment(household_id=ID["hh_okafor"], schedule_id=ID["schedule"], valid_during=Range(date(2026, 1, 1), None, bounds="[)")),
        ])
        session.commit()
        print("Seeded. Try the Q3 fee run:")
        print(f"  curl -s -X POST localhost:8000/fee-runs -H 'content-type: application/json' "
              f"-d '{{\"household_id\":\"{ID['hh_tremblay']}\",\"period_start\":\"2026-07-01\",\"period_end\":\"2026-09-30\"}}'")


if __name__ == "__main__":
    main()