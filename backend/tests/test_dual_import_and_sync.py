import io
from datetime import date, time

from openpyxl import Workbook

from app.importers import At4532XlsxImporter, Gpm8213TxtImporter


def _at4532_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Relatório sintético AT4532"])
    sheet.append(["Data", "Hora", "CH1 [°C]", "CH2 [°F]", "CH32 [°C]", "Ambient [°C]"])
    sheet.append([date(2026, 1, 2), time(10, 0, 0), 30.5, 86.0, 44.2, 25.0])
    sheet.append([date(2026, 1, 2), time(10, 0, 1), 31.0, "OL", 44.4, 25.1])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _gpm8213_text() -> bytes:
    return (
        b"Synthetic GPM-8213 export\n"
        b"Date;Time;Voltage [V];Current [mA];Active Power [kW];Apparent Power [VA];"
        b"Reactive Power [var];Power Factor;Voltage Frequency [Hz];Current Frequency [Hz]\n"
        b"02/01/2026;10:00:00;220.0;500;0.110;115;20;0.956;60;60\n"
        b"02/01/2026;10:00:01;221.0;510;0.112;117;22;0.957;60;60\n"
    )


def test_gpm_importer_normalizes_and_preserves_original_values():
    result = Gpm8213TxtImporter().parse(_gpm8213_text())
    assert not result.errors
    assert len(result.readings) == 2
    first = result.readings[0]
    assert first.current_a == 0.5
    assert first.active_power_w == 110
    assert first.original_values["active_power"] == 0.110
    assert first.original_units["active_power"] == "kW"


def test_at4532_importer_detects_32_channels_and_quality():
    result = At4532XlsxImporter().parse(_at4532_workbook())
    assert not result.errors
    assert len(result.readings) == 2
    assert {item.channel for item in result.readings[0].channels} == {1, 2, 32}
    assert result.readings[0].channels[1].temperature_c == 30
    assert result.readings[1].channels[1].quality == "overload"


def test_preview_confirm_and_synchronize_imports(client, auth_headers):
    preview = client.post(
        "/api/v1/imports/gpm8213/preview",
        headers=auth_headers,
        files={"file": ("gpm8213.txt", _gpm8213_text(), "text/plain")},
    )
    assert preview.status_code == 200
    assert preview.json()["valid_rows"] == 2

    response = client.post(
        "/api/v1/imports/session",
        headers=auth_headers,
        data={"name": "Ensaio sintético integrado", "grid_ms": "1000", "tolerance_ms": "1500"},
        files={
            "at4532_file": (
                "at4532.xlsx",
                _at4532_workbook(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "gpm8213_file": ("gpm8213.txt", _gpm8213_text(), "text/plain"),
        },
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["session_id"]
    synchronized = client.get(
        f"/api/v1/sessions/{session_id}/synchronized-series?grid_ms=1000&tolerance_ms=1500",
        headers=auth_headers,
    )
    assert synchronized.status_code == 200
    payload = synchronized.json()
    assert payload["metrics"]["matched_points"] == 2
    assert payload["points"][0]["active_power_w"] == 110
    assert payload["points"][0]["temperatures_c"]["32"] == 44.2


def test_upload_rejects_wrong_signature(client, auth_headers):
    response = client.post(
        "/api/v1/imports/at4532/preview",
        headers=auth_headers,
        files={"file": ("fake.xlsx", b"not-a-zip", "application/octet-stream")},
    )
    assert response.status_code == 422
