from collections import defaultdict
from collections.abc import Sequence

RRF_K = 60  # the constant from Cormack et al.; dampens the weight of top ranks


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Merge ranked lists by rank, not score: full-text and cosine scores live on different scales."""
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] += 1 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
