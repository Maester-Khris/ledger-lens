import enum
import uuid

# Pure types shared by models, DAO and pure logic. No SQLAlchemy or FastAPI imports here.

DEMO_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class Direction(str, enum.Enum):
    debit = "debit"
    credit = "credit"


class NormalBalance(str, enum.Enum):
    debit = "debit"
    credit = "credit"


class PostingSource(str, enum.Enum):
    api = "api"
    fee_run = "fee_run"
    ai_tool = "ai_tool"
    stress_test = "stress_test"
