"""Explicit, bounded publication of approved results. No acquisition access."""

import base64
import hashlib
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import HTTPException

from app.portal.contracts import MAX_SNAPSHOT_BYTES, ResultSnapshot, canonical_bytes


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def portal_origin():
    origin = os.environ.get("THERMOPOWER_RESULTS_PORTAL_URL", "").rstrip("/")
    parsed = urlsplit(origin)
    local_test = os.environ.get(
        "THERMOPOWER_RESULTS_PORTAL_LOCAL_TEST"
    ) == "1" and parsed.hostname in {"127.0.0.1", "localhost"}
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
        or (parsed.scheme != "https" and not (parsed.scheme == "http" and local_test))
    ):
        raise HTTPException(
            503, "Configure o endereço HTTPS do portal de resultados antes de publicar."
        )
    return origin


def portal_request(origin, method, path, content=None):
    if origin != portal_origin():
        raise HTTPException(
            503,
            "O endereço difere do portal deste link. Restaure a configuração para revogar.",
        )
    key = os.environ.get("THERMOPOWER_RESULTS_PORTAL_PUBLISH_KEY", "")
    if len(key) < 32:
        raise HTTPException(503, "Configure a credencial de publicação do portal no ambiente.")
    request = Request(
        origin + path,
        data=content,
        method=method,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            if response.status not in {200, 201, 204}:
                raise HTTPException(503, "Portal não confirmou a operação. Tente novamente.")
    except (HTTPError, URLError, TimeoutError, OSError):
        raise HTTPException(
            503,
            "Não foi possível confirmar a operação no portal. Confira a conexão e tente novamente.",
        ) from None


def encode_document(content):
    return {
        "content": base64.b64encode(content).decode(),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def publish_snapshot(origin, snapshot):
    validated = ResultSnapshot.model_validate(snapshot)
    content = canonical_bytes(validated.model_dump(mode="json"))
    if len(content) > MAX_SNAPSHOT_BYTES:
        raise HTTPException(413, "Resultado excede 25 MiB. Reduza o período, canais ou downloads.")
    portal_request(origin, "POST", "/portal/v1/results", content)


def revoke_publication(origin, token_hash):
    portal_request(origin, "DELETE", "/portal/v1/results/" + token_hash)
