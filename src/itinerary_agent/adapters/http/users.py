"""HTTP 用户目录适配器。"""

from urllib.parse import quote

from itinerary_agent.adapters.http.client import JsonHttpClient
from itinerary_agent.domain.models import UserProfile


class HttpUserDirectory:
    def __init__(self, client: JsonHttpClient):
        self.client = client

    async def get(self, user_id: str) -> UserProfile:
        data = await self.client.get(f"/users/{quote(user_id, safe='')}")
        return UserProfile.model_validate(data)
