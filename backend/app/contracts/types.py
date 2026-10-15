import enum


class FieldRouting(str, enum.Enum):
    accepted = "accepted"
    needs_review = "needs_review"


class ReviewDecision(str, enum.Enum):
    confirmed = "confirmed"
    corrected = "corrected"
    rejected = "rejected"
