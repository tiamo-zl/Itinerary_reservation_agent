"""评测指标。"""


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def recall_at_k(expected: list[str], returned: list[str], k: int) -> float:
    if not expected:
        return 1.0
    hits = len(set(expected) & set(returned[:k]))
    return hits / len(expected)


def reciprocal_rank(expected: list[str], returned: list[str]) -> float:
    if not expected:
        return 1.0
    expected_set = set(expected)
    for rank, clause_id in enumerate(returned, start=1):
        if clause_id in expected_set:
            return 1.0 / rank
    return 0.0


def precision(expected: list[str], returned: list[str]) -> float:
    if not returned:
        return 1.0 if not expected else 0.0
    return len(set(expected) & set(returned)) / len(returned)
