from datetime import timedelta, timezone

from test_period_reports import _payload, _seed_period_data


def test_official_window_and_annotations_preserve_history(client, auth_headers):
    start, end, ids = _seed_period_data()
    base = f"/api/v1/sessions/{ids[0]}"
    assert client.get(base, headers=auth_headers).json()["analysis_period"] is None
    window = {
        "start": (start + timedelta(seconds=5))
        .astimezone(timezone(timedelta(hours=-3)))
        .isoformat(),
        "end": (start + timedelta(seconds=15))
        .astimezone(timezone(timedelta(hours=-3)))
        .isoformat(),
        "label": "Estabilizado",
    }
    saved = client.put(base + "/analysis-period", json=window, headers=auth_headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["selected_by"]
    assert saved.json()["start"] == (start + timedelta(seconds=5)).isoformat()
    assert saved.json()["end"] == (start + timedelta(seconds=15)).isoformat()
    assert client.get(base, headers=auth_headers).json()["analysis_period"] == saved.json()
    payload = {**_payload(start, end), "session_ids": [ids[0]], **window}
    preview = client.post("/api/v1/reports/period/preview", json=payload, headers=auth_headers)
    assert preview.status_code == 200, preview.text
    stats = preview.json()["statistics"]
    assert stats["electrical"]["active_power_w"]["mean"] == 200
    assert stats["electrical"]["active_power_w"]["max"] == 200
    assert stats["electrical"]["energy_wh"] == 0
    assert stats["general"]["analyzed_period_seconds"] == 10
    assert stats["temperature"]["max"] == 32
    assert stats["channels"][0]["mean"] == 32
    csv = client.post(
        "/api/v1/reports/period/csv?dataset=electrical", json=payload, headers=auth_headers
    )
    assert csv.status_code == 200
    assert "300.0" not in csv.text and "200.0" in csv.text
    legacy_export = client.get(f"/api/v1/reports/sessions/{ids[0]}.csv", headers=auth_headers)
    assert legacy_export.status_code == 200
    assert "300.0" not in legacy_export.text and "200.0" in legacy_export.text
    event = {
        "timestamp": (start + timedelta(seconds=10, milliseconds=125))
        .astimezone(timezone(timedelta(hours=-3)))
        .isoformat(),
        "title": "Desligamento",
        "kind": "shutdown",
        "description": "Observado na bancada",
    }
    response = client.post(base + "/annotations", json=event, headers=auth_headers)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["timestamp"].startswith("2026-01-15T13:00:10.125")
    assert client.get(base + "/annotations", headers=auth_headers).json()["total"] == 1
    assert (
        client.put(
            base + f"/annotations/{item['id']}",
            json={**event, "title": "Revisado"},
            headers=auth_headers,
        ).status_code
        == 200
    )
    assert (
        client.get(base + "/annotations", headers=auth_headers)
        .json()["items"][0]["timestamp"]
        .startswith("2026-01-15T13:00:10.125")
    )
    assert (
        client.post(
            base + "/annotations",
            json={**event, "timestamp": (end + timedelta(seconds=1)).isoformat()},
            headers=auth_headers,
        ).status_code
        == 422
    )
    assert (
        client.put(
            base + "/analysis-period",
            json={**window, "end": start.isoformat()},
            headers=auth_headers,
        ).status_code
        == 422
    )
    # Full-session analysis is temporary and does not erase the saved preference.
    full = client.post(
        "/api/v1/reports/period/preview",
        json={**_payload(start, end), "session_ids": [ids[0]]},
        headers=auth_headers,
    )
    assert full.json()["statistics"]["electrical"]["active_power_w"]["max"] == 300
    assert client.get(base, headers=auth_headers).json()["analysis_period"] == saved.json()
    assert (
        client.delete(base + f"/annotations/{item['id']}", headers=auth_headers).status_code == 204
    )
    # Removing only the preference restores legacy full exports, preserving readings.
    assert client.delete(base + "/analysis-period", headers=auth_headers).status_code == 204
    assert client.get(base, headers=auth_headers).json()["analysis_period"] is None
    restored = client.get(f"/api/v1/reports/sessions/{ids[0]}.csv", headers=auth_headers)
    assert "300.0" in restored.text and "200.0" in restored.text
    assert client.delete(base + "/analysis-period", headers=auth_headers).status_code == 204
