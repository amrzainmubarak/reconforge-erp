"""Count actual HTTP registrations, retaining duplicates and inclusion prefixes.

FastAPI 0.137 preserves included routers instead of copying their routes. Its
route-context iterator resolves that topology; older releases retain flat routes.
No OpenAPI dictionary is used, because duplicate operations would be overwritten.
"""

from collections import Counter

from fastapi import FastAPI, routing


def registered_http_operations(app: FastAPI) -> Counter[tuple[str, str]]:
    resolve = getattr(routing, "iter_route_contexts", None)
    routes = resolve(app.routes) if resolve is not None else app.routes
    operations: Counter[tuple[str, str]] = Counter()
    for route in routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        path = getattr(route, "path", None)
        if not isinstance(path, str):
            raise ValueError("An HTTP registration lacks its effective path.")
        for method in methods:
            operations[(method, path)] += 1
    return operations
