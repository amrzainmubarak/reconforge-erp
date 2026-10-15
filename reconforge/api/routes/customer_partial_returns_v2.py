"""Server-fixed remainder allocation over the shared governed CR2 routes."""

from fastapi import APIRouter, Depends, Request
from fastapi.routing import APIRoute

from reconforge.api.routes import customer_partial_returns


def _select_protocol(request: Request) -> None:
    # Request state is assigned by this router, never a body or header selector.
    request.state.customer_partial_return_protocol_version = 2


router = APIRouter()
for route in customer_partial_returns.router.routes:
    if not isinstance(route, APIRoute):
        raise RuntimeError("The shared partial-return route contract changed.")
    router.add_api_route(route.path, route.endpoint, methods=route.methods,
                         dependencies=[Depends(_select_protocol), *route.dependencies],
                         response_model=route.response_model, status_code=route.status_code,
                         tags=route.tags, name=route.name)
