"""模拟用户/权限系统。

真实环境由企业用户中心返回职级、部门与角色；这里只保留 demo 必需字段。
"""

from itinerary_agent.domain.models import UserProfile


class MockUserDirectory:
    def __init__(self):
        self._users = {
            "u001": UserProfile(
                user_id="u001", tenant_id="demo-company", name="张三",
                employee_level="L2", department="销售", city="上海",
                roles=["employee"],
            ),
            "u002": UserProfile(
                user_id="u002", tenant_id="demo-company", name="李四",
                employee_level="L3", department="财务", city="上海",
                roles=["employee", "approver"],
            ),
        }

    async def get(self, user_id: str) -> UserProfile:
        return self._users[user_id]
