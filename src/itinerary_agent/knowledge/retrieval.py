"""混合召回与融合。

关键词（FTS5）和向量召回各有盲区：前者精确、后者语义。
RRF 只使用排名，不需要把两路分数归一化。
"""

CITY_TIERS = {
    "北京": 1, "上海": 1, "广州": 1, "深圳": 1,
    "杭州": 2, "成都": 2, "武汉": 2, "南京": 2,
}


def rrf_fuse(keyword_ids: list[str], dense_ids: list[str], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion：按排名累加 1/(k+rank)。"""
    scores: dict[str, float] = {}
    for rank, clause_id in enumerate(keyword_ids, start=1):
        scores[clause_id] = scores.get(clause_id, 0.0) + 1.0 / (k + rank)
    for rank, clause_id in enumerate(dense_ids, start=1):
        scores[clause_id] = scores.get(clause_id, 0.0) + 1.0 / (k + rank)
    return [
        clause_id
        for clause_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]
