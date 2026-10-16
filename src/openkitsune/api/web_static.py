"""Serve the Web shell fresh while allowing normal caching of hashed assets."""

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class WebStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        # A distinct return URL also avoids already-cached /web/ documents that
        # predate our cache policy. Keep the instruction in the URL fragment.
        if path.rstrip("/") == "marketplace-return":
            path = "index.html"
        fresh = path in {"", ".", "index.html", "sw.js"}
        if fresh:
            scope = {
                **scope,
                "headers": [
                    (key, value)
                    for key, value in scope["headers"]
                    if key.lower() not in {b"if-none-match", b"if-modified-since"}
                ],
            }
        response = await super().get_response(path, scope)
        if fresh or response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response
