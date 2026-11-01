"""Milvus 条款向量存储。

只存 dense 向量和检索所需元数据；条款树/表格/引用边仍在 SQLite，
这样向量召回后再做结构化扩展。
"""

from pymilvus import DataType, MilvusClient

from itinerary_agent.infra.config import Settings


class MilvusClauseStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = MilvusClient(
            uri=settings.milvus_uri,
            token=settings.milvus_token.get_secret_value(),
        )

    def ensure_collection(self) -> None:
        name = self.settings.milvus_collection
        if self.client.has_collection(name):
            return

        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("clause_id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("tenant_id", DataType.VARCHAR, max_length=64, is_partition_key=True)
        schema.add_field("doc_id", DataType.VARCHAR, max_length=64)
        schema.add_field("policy_version", DataType.VARCHAR, max_length=32)
        schema.add_field("clause_type", DataType.VARCHAR, max_length=32)
        schema.add_field("path", DataType.VARCHAR, max_length=512)
        schema.add_field("parent_id", DataType.VARCHAR, max_length=64)
        schema.add_field("title", DataType.VARCHAR, max_length=256)
        schema.add_field("text", DataType.VARCHAR, max_length=8192)
        schema.add_field("table_id", DataType.VARCHAR, max_length=64)
        schema.add_field("refs", DataType.JSON)
        schema.add_field("effective_from", DataType.VARCHAR, max_length=10)
        schema.add_field("effective_to", DataType.VARCHAR, max_length=10)
        schema.add_field(
            "embedding", DataType.FLOAT_VECTOR,
            dim=self.settings.embedding_dimensions,
        )

        index = self.client.prepare_index_params()
        index.add_index(
            field_name="embedding", index_type="HNSW", metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        self.client.create_collection(name, schema=schema, index_params=index)

    def reset(self) -> None:
        """重建 collection；用于全量 reindex。"""
        if self.client.has_collection(self.settings.milvus_collection):
            self.client.drop_collection(self.settings.milvus_collection)
        self.ensure_collection()

    def upsert(self, rows: list[dict]) -> None:
        # 以 clause_id 为主键幂等写入；重复入库不会产生重复向量。
        self.client.upsert(collection_name=self.settings.milvus_collection, data=rows)

    def search(self, tenant_id: str, policy_version: str, vector: list[float],
               limit: int = 10) -> list[dict]:
        results = self.client.search(
            collection_name=self.settings.milvus_collection,
            data=[vector],
            anns_field="embedding",
            limit=limit,
            filter=(
                f'tenant_id == "{tenant_id}" and '
                f'policy_version == "{policy_version}"'
            ),
            output_fields=["clause_id", "title", "text", "table_id", "refs"],
        )
        return [
            {"clause_id": hit["id"], "score": hit["distance"], **hit["entity"]}
            for hit in results[0]
        ]
