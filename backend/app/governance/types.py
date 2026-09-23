import enum


class ToolDecision(str, enum.Enum):
    approved = "approved"
    rejected = "rejected"