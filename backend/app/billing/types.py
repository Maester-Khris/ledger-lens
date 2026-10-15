import enum


class FeeMethod(str, enum.Enum):
    graduated = "graduated"  # each tranche billed at its own tier's rate
    cliff = "cliff"  # the whole value billed at the rate of the tier it reaches
