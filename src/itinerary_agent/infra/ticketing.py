"""工单适配器。

demo 用本地编号；生产替换成 Gitee/GitHub Issues/Jira 适配器即可。
"""


class LocalTicketAdapter:
    async def create(self, badcase: dict) -> str:
        return f"LOCAL-{badcase['badcase_id'][:8]}"

    async def close(self, ticket_ref: str, comment: str) -> None:
        # 本地 demo 不需要外部状态流转；badcases 表本身是副本。
        return None
