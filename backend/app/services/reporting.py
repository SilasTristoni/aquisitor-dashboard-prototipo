from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.entities import MeasurementSession, Report


def _session_report(db: Session, session_id: int):
    from app.schemas.contracts import PeriodReportRequest
    from app.services.period_reporting import PeriodReportDataService
    from app.services.session_clock import utc

    session = db.get(MeasurementSession, session_id)
    if session is None:
        raise ValueError("Sessão não encontrada")
    start = utc(session.started_at)
    end = utc(session.ended_at) if session.ended_at else datetime.now(UTC)
    request = PeriodReportRequest(
        start=start,
        end=max(end, start + timedelta(microseconds=1)),
        session_ids=[session_id],
        title=f"Relatório da sessão: {session.name}",
        use_device_timestamp=False,
    )
    return PeriodReportDataService(db).collect(request), request


def _record(db: Session, session_id: int, user_id: int, report_type: str, content: bytes) -> bytes:
    db.add(Report(session_id=session_id, type=report_type, generated_by=user_id))
    db.commit()
    return content


def create_xlsx(db: Session, session_id: int, user_id: int) -> bytes:
    from app.services.period_workbook import render_period_xlsx

    data, request = _session_report(db, session_id)
    return _record(db, session_id, user_id, "xlsx", render_period_xlsx(data, request))


def create_pdf(db: Session, session_id: int, user_id: int, orientation: str = "landscape") -> bytes:
    from app.services.period_documents import render_period_pdf

    data, request = _session_report(db, session_id)
    request = request.model_copy(update={"orientation": orientation})
    return _record(db, session_id, user_id, "pdf", render_period_pdf(data, request))


def create_chart_image(db: Session, session_id: int, user_id: int, image_type: str) -> bytes:
    from app.services.period_documents import render_period_chart

    data, request = _session_report(db, session_id)
    return _record(
        db, session_id, user_id, image_type, render_period_chart(data, request, image_type)
    )


def create_csv(db: Session, session_id: int, user_id: int) -> bytes:
    from app.services.period_workbook import render_period_csv

    data, request = _session_report(db, session_id)
    return _record(db, session_id, user_id, "csv", render_period_csv(data, request))
