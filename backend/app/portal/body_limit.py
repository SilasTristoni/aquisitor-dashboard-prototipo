import anyio
from starlette.responses import JSONResponse

from app.portal.contracts import MAX_SNAPSHOT_BYTES
from app.services.share_policy import PRIVATE_HEADERS


class BoundedBody:
    """Bound request memory even with chunked transfer, before JSON validation."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PATCH", "PUT"}:
            return await self.app(scope, receive, send)
        limit = MAX_SNAPSHOT_BYTES if scope["path"] == "/portal/v1/results" else 4096
        body = bytearray()
        try:
            with anyio.fail_after(15):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > limit:
                        response = JSONResponse(
                            {"detail": "Solicitação excede o limite de tamanho"},
                            status_code=413,
                            headers=PRIVATE_HEADERS,
                        )
                        return await response(scope, receive, send)
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            response = JSONResponse(
                {"detail": "Tempo de envio excedido"}, status_code=408, headers=PRIVATE_HEADERS
            )
            return await response(scope, receive, send)
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
