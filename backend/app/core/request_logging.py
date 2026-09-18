from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.core.observability import category_for, new_correlation_id, request_context, sanitize
from app.services.support import audit_event

logger = logging.getLogger(__name__)


def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    context = getattr(request.state, "support_context", None) or {
        "correlation_id": new_correlation_id(),
        "category": "APPLICATION",
        "operation": request.method,
        "endpoint": request.url.path,
    }
    context["error_code"] = context["correlation_id"]
    context["exception_type"] = type(exc).__name__
    context["technical_message"] = sanitize(str(exc))[:2000]
    executive = "executive." in request.url.path
    message = (
        "Não foi possível gerar o resumo executivo."
        if executive
        else "Não foi possível gerar o arquivo."
        if context["category"] == "EXPORT"
        else "Não foi possível concluir a operação."
    )
    context["human_message"] = message
    logger.error("Unexpected operation failure", exc_info=exc, extra=context)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "status": 500,
                "message": message,
                "correlation_id": context["correlation_id"],
                "error_code": context["error_code"],
                "action": "Tente novamente. Se o problema continuar, exporte o diagnóstico.",
            }
        },
        headers={"X-Correlation-ID": context["correlation_id"]},
    )


async def observe_request(request: Request, call_next):
    path = request.url.path
    export = "/reports/" in path and not path.endswith("/preview")
    category = "EXPORT" if export else category_for(path)
    context = {
        "correlation_id": new_correlation_id("EXP" if export else "APP"),
        "category": category,
        "operation": f"{request.method} {path}",
        "endpoint": path,
        "started_at": datetime.now(UTC).isoformat(),
    }
    for resource, key in (("sessions", "session_id"), ("devices", "device_id")):
        if match := re.search(rf"/{resource}/(\d+)(?:[/.]|$)", path):
            context[key] = int(match[1])
    request.state.support_context = context
    token = request_context.set(context)
    try:
        # Read only the two non-sensitive report selectors; never log the body or title.
        if export and request.method == "POST":
            try:
                body = await request.json()
                ids = body.get("session_ids", []) if isinstance(body, dict) else []
                if len(ids) == 1 and isinstance(ids[0], int):
                    context["session_id"] = ids[0]
            except (ValueError, TypeError):
                pass
        if export:
            context["report_type"] = path.rsplit("/", 1)[-1]
            logger.info("Export started", extra={"operation": "export.start"})
        try:
            response = await call_next(request)
        except Exception as exc:
            response = unexpected_error(request, exc)
        context["completed_at"] = datetime.now(UTC).isoformat()
        context["status"] = "completed" if response.status_code < 400 else "failed"
        context["http_status"] = response.status_code
        if response.status_code >= 400:
            context.setdefault("error_code", context["correlation_id"])
        if export or response.status_code >= 500:
            if disposition := response.headers.get("Content-Disposition"):
                context["file"] = (
                    disposition.split(";")[1].strip() if ";" in disposition else disposition
                )
            failed = response.status_code >= 400
            message = context.get(
                "human_message",
                "Exportação não concluída." if failed else "Arquivo gerado com sucesso.",
            )
            logger.log(
                logging.ERROR if failed else logging.INFO,
                message,
                extra={"operation": "export.finish" if export else "request.finish"},
            )
            await run_in_threadpool(
                audit_event, context.copy(), message, "error" if failed else "info"
            )
        response.headers["X-Correlation-ID"] = context["correlation_id"]
        return response
    finally:
        request_context.reset(token)
