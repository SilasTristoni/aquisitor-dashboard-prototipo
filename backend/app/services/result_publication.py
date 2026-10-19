"""Explicit, bounded publication of approved results. No acquisition access."""

import base64
import hashlib
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import HTTPException

from app.portal.contracts import MAX_SNAPSHOT_BYTES, ResultSnapshot, canonical_bytes
from app.services.portal_configuration import PortalConfiguration, configuration, validate_origin


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def portal_origin():
    try:
        return validate_origin(
            configuration().get("url", ""),
            os.environ.get("THERMOPOWER_RESULTS_PORTAL_LOCAL_TEST") == "1",
        )
    except ValueError:
        raise HTTPException(
            503, "Configure o endereço HTTPS do portal de resultados antes de publicar."
        ) from None


def installation_id():
    return configuration().get("installation_id", "")


def portal_request(origin, method, path, content=None):
    if origin != portal_origin():
        raise HTTPException(503, "Restaure o endereço original do portal para gerenciar este link.")
    config = configuration()
    try:
        # Origin was validated above, including the explicit loopback test exception.
        PortalConfiguration.model_validate({**config, "url": "https://validation.invalid"})
    except ValueError:
        raise HTTPException(503, "Configure a credencial específica desta instalação.") from None
    key = config.get("credential", "")
    identity = config.get("installation_id", "")
    if len(key) < 32 or not identity:
        raise HTTPException(503, "Configure a credencial específica desta instalação no portal.")
    request = Request(
        origin + path,
        data=content,
        method=method,
        headers={
            "Authorization": "Bearer " + identity + "." + key,
            "Content-Type": "application/json",
        },
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            if response.status not in {200, 201, 204}:
                raise HTTPException(503, "Portal não confirmou a operação. Tente novamente.")
            if response.status == 204:
                return None
            raw = response.read(4097)
            if len(raw) > 4096:
                raise ValueError("Oversized response")
            return json.loads(raw)
    except HTTPError as exc:
        messages = {
            401: "Credencial da instalação recusada. Solicite revisão ao administrador.",
            404: "Publicação indisponível para esta instalação.",
            409: "Operação em conflito no portal. Confira o estado do compartilhamento.",
            413: "Resultado excede o limite do portal. Reduza período ou downloads.",
            422: "O portal recusou os dados enviados. Confira a versão e as permissões.",
            429: "Limite do portal atingido. Aguarde um minuto antes de tentar novamente.",
        }
        status = exc.code if exc.code in messages else 503
        raise HTTPException(
            status, messages.get(exc.code, "Portal indisponível. Tente novamente.")
        ) from None
    except (URLError, TimeoutError, OSError, ValueError):
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
    receipt = portal_request(origin, "POST", "/portal/v1/results", content)
    try:
        public_origin = validate_origin(receipt["public_origin"])
        if receipt["token_hash"] != validated.token_hash or receipt["path"] != "/compartilhado":
            raise ValueError("Invalid receipt")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, "Confirmação inválida do portal. Tente novamente.") from None
    return {**receipt, "public_origin": public_origin}


def revoke_publication(origin, token_hash):
    portal_request(origin, "DELETE", "/portal/v1/results/" + token_hash)


def update_publication_permissions(origin, token_hash, payload):
    result = portal_request(
        origin,
        "PATCH",
        "/portal/v1/results/" + token_hash + "/permissions",
        canonical_bytes(payload),
    )
    if not isinstance(result, dict) or result.get("revision") != payload["revision"]:
        raise HTTPException(503, "Atualização de permissões não confirmada. Tente novamente.")
