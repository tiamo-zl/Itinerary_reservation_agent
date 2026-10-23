from dataclasses import dataclass

from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.db import Database
from itinerary_agent.observability.tracing import TraceRecorder


@dataclass
class Container:
    settings: Settings
    db: Database
    traces: TraceRecorder

    async def start(self) -> None:
        await self.db.connect()

    async def stop(self) -> None:
        await self.db.close()


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    db = Database(settings.sqlite_path)
    return Container(settings=settings, db=db, traces=TraceRecorder(db))
