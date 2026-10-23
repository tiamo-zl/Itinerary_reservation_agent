from contextlib import asynccontextmanager

from fastapi import FastAPI

from itinerary_agent.infra.container import Container


def create_app(container: Container) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await container.start()
        yield
        await container.stop()

    app = FastAPI(title="Itinerary Reservation Agent", lifespan=lifespan)
    app.state.container = container

    @app.get("/health")
    async def health():
        return {"status": "ok", "env": container.settings.env}

    return app
