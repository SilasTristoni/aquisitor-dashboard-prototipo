"""Final security review: synthetic accounts/streams, never hardware."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import create_access_token, hash_password
from app.models.entities import User
from app.services.websocket import websocket_hub


def create_user(role="viewer", active=True):
    with SessionLocal() as db:
        user = User(
            name="Synthetic review",
            email=f"{role}@review.example.com",
            role=role,
            active=active,
            password_hash=hash_password("synthetic-review-password"),
        )
        db.add(user)
        db.commit()
        return user.id, create_access_token(str(user.id), role)


def publish(client, session_id=11):
    # Same hub/event shape used by the product, without invoking an adapter.
    client.portal.call(
        websocket_hub.publish,
        "measurement.created",
        {
            "session_id": session_id,
            "device_id": 7,
            "active_power_w": 123.0,
            "received_timestamp": "2026-10-12T12:00:00+00:00",
            "raw_payload": {"synthetic": True},
        },
    )


@pytest.mark.parametrize("role", ["admin", "operator", "viewer"])
def test_active_roles_keep_existing_shared_laboratory_stream(client, role):
    _, token = create_user(role)
    with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "connection.ready"
        for session_id in [11, 12]:
            publish(client, session_id)
            message = ws.receive_json()
            assert message["type"] == "measurement.created"
            assert message["payload"]["session_id"] == session_id
            assert message["payload"]["active_power_w"] == 123.0


@pytest.mark.parametrize("credential", ["missing", "invalid", "expired", "share"])
def test_websocket_rejects_missing_invalid_expired_and_share_tokens(client, credential):
    token = "not-a-jwt" if credential != "share" else "synthetic-share-token" * 3
    if credential == "expired":
        token = jwt.encode(
            {"sub": "1", "exp": datetime.now(UTC) - timedelta(seconds=1)},
            get_settings().jwt_secret,
            algorithm="HS256",
        )
    url = "/api/v1/ws" if credential == "missing" else f"/api/v1/ws?token={token}"
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url) as ws:
            ws.receive_json()
    assert exc.value.code in {1008, 4401}


@pytest.mark.parametrize("state", ["inactive", "deleted"])
def test_websocket_rejects_revoked_users_at_handshake(client, state):
    user_id, token = create_user(active=state != "inactive")
    if state == "deleted":
        with SessionLocal() as db:
            db.delete(db.get(User, user_id))
            db.commit()
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
            assert ws.receive_json()["type"] != "connection.ready"
    assert exc.value.code == 4401


@pytest.mark.parametrize("state", ["inactive", "deleted", "expired"])
def test_open_websocket_stops_data_after_revocation_or_expiry(client, monkeypatch, state):
    import jwt.api_jwt

    user_id, token = create_user()
    with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "connection.ready"
        publish(client)
        assert ws.receive_json()["payload"]["active_power_w"] == 123.0
        if state == "expired":
            future = datetime.now(UTC) + timedelta(days=1)

            class FutureDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return future

            monkeypatch.setattr(jwt.api_jwt, "datetime", FutureDatetime)
        else:
            with SessionLocal() as db:
                user = db.get(User, user_id)
                if state == "deleted":
                    db.delete(user)
                else:
                    user.active = False
                db.commit()
        publish(client, session_id=99)
        with pytest.raises(WebSocketDisconnect) as exc:
            message = ws.receive_json()
            pytest.fail(f"Unauthorized stream remained readable: {message['type']}")
        assert exc.value.code == 4401


def test_existing_account_password_hash_and_http_token_remain_compatible(client):
    user_id, token = create_user("operator")
    with SessionLocal() as db:
        original_hash = db.get(User, user_id).password_hash
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "operator@review.example.com",
            "password": "synthetic-review-password",
        },
    )
    assert response.status_code == 200
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token}).status_code
        == 200
    )
    with SessionLocal() as db:
        assert db.get(User, user_id).password_hash == original_hash


@pytest.mark.parametrize("claims", [{"sub": "1"}, {"sub": "invalid"}, {}, {"sub": "9" * 30}])
def test_websocket_rejects_malformed_subject_or_missing_expiration(client, claims):
    if claims != {"sub": "1"}:
        claims = {**claims, "exp": datetime.now(UTC) + timedelta(minutes=1)}
    token = jwt.encode(claims, get_settings().jwt_secret, algorithm="HS256")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_websocket_fails_closed_when_authorization_database_fails(client, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from app.api import deps

    _, token = create_user()
    with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "connection.ready"

        def unavailable():
            raise SQLAlchemyError("Synthetic database outage")

        monkeypatch.setattr(deps, "SessionLocal", unavailable)
        publish(client)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1011


def test_idle_websocket_closes_at_token_expiration(client):
    import time

    user_id, _ = create_user()
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(seconds=2)},
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    started = time.monotonic()
    with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "connection.ready"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    assert time.monotonic() - started < 5


@pytest.mark.parametrize("role", ["admin", "operator", "viewer"])
def test_http_expired_tokens_are_rejected_for_all_roles(client, role):
    user_id, _ = create_user(role)
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) - timedelta(seconds=1)},
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token}).status_code
        == 401
    )
