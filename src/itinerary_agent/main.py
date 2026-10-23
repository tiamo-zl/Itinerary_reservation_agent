from itinerary_agent.api.app import create_app
from itinerary_agent.infra.container import build_container

app = create_app(build_container())
