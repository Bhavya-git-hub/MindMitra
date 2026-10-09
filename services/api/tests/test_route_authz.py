"""Every API route is either explicitly public or guarded by an authorization dependency."""

from collections.abc import Iterator
from typing import Any

from fastapi.routing import APIRoute

from app.api.deps import AUTHZ_MARKER
from app.api.main import API_PREFIX, PUBLIC_ROUTES, ROUTERS, create_app


def _api_routes() -> Iterator[tuple[str, str, APIRoute]]:
    for router in ROUTERS:
        for route in router.routes:
            assert isinstance(route, APIRoute)
            for method in route.methods or ():
                yield method, API_PREFIX + route.path, route


def _guards(route: APIRoute) -> list[str]:
    found: list[str] = []

    def walk(dependant: Any) -> None:
        call = getattr(dependant, "call", None)
        if call is not None and hasattr(call, AUTHZ_MARKER):
            found.append(getattr(call, AUTHZ_MARKER))
        for sub in dependant.dependencies:
            walk(sub)

    walk(route.dependant)
    return found


def test_every_route_is_guarded_or_explicitly_public() -> None:
    unguarded = [
        (method, path)
        for method, path, route in _api_routes()
        if not _guards(route) and (method, path) not in PUBLIC_ROUTES
    ]
    assert unguarded == [], f"routes without an authorization guard: {unguarded}"


def test_public_routes_carry_no_guard_and_all_exist() -> None:
    routes = {(method, path): route for method, path, route in _api_routes()}
    for key in PUBLIC_ROUTES:
        assert key in routes, f"PUBLIC_ROUTES lists a route that does not exist: {key}"
        assert not _guards(routes[key]), f"public route unexpectedly guarded: {key}"


def test_routers_cover_the_whole_app() -> None:
    """ROUTERS (what the coverage test walks) is exactly what the app serves."""
    schema = create_app().openapi()
    served = {(method.upper(), path) for path, ops in schema["paths"].items() for method in ops}
    walked = {(method, path) for method, path, _ in _api_routes() if method != "HEAD"}
    assert served == walked
