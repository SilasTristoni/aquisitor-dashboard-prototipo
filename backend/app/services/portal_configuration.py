"""Installation configuration. Windows secrets live in Credential Manager, never SQLite."""

import ctypes
import json
import os
from ctypes import wintypes
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

TARGET = "ThermoPower/ResultsPortal/v1"


def validate_origin(value: str, local_test=False) -> str:
    value = value.rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        valid = (
            parsed.hostname
            and not any(
                (parsed.username, parsed.password, parsed.query, parsed.fragment, parsed.path)
            )
            and not any(char.isspace() for char in value)
            and (port is None or 0 < port < 65536)
            and (
                parsed.scheme == "https"
                or (
                    local_test
                    and parsed.scheme == "http"
                    and parsed.hostname in {"localhost", "127.0.0.1"}
                )
            )
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Informe uma origem HTTPS sem caminho, credenciais ou parâmetros")
    return value


class PortalConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=512)
    installation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    credential: SecretStr = Field(min_length=32, max_length=256)

    @field_validator("url")
    @classmethod
    def https_origin(cls, value):
        return validate_origin(value)

    @field_validator("credential")
    @classmethod
    def credential_format(cls, value):
        secret = value.get_secret_value()
        if not secret.isascii() or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for c in secret
        ):
            raise ValueError("Credencial inválida")
        return value


class Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def vault_api():
    if os.name != "nt":
        raise HTTPException(503, "Configuração segura pela interface requer Windows.")
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credential)),
    ]
    api.CredReadW.restype = wintypes.BOOL
    api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api


def read_vault():
    if os.name != "nt":
        return {}
    api = vault_api()
    pointer = ctypes.POINTER(Credential)()
    if not api.CredReadW(TARGET, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return {}
        raise HTTPException(503, "Não foi possível ler a credencial protegida do Windows.")
    try:
        raw = ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Invalid configuration")
        return value
    except (ValueError, UnicodeError):
        raise HTTPException(503, "Configuração protegida inválida. Configure novamente.") from None
    finally:
        api.CredFree(pointer)


def save_configuration(value: PortalConfiguration):
    if os.environ.get("THERMOPOWER_RESULTS_PORTAL_URL"):
        raise HTTPException(409, "A configuração é gerenciada pelo ambiente. Ajuste-a na origem.")
    api = vault_api()
    raw = json.dumps(
        {
            **value.model_dump(exclude={"credential"}),
            "credential": value.credential.get_secret_value(),
        }
    ).encode()
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    record = Credential(
        Type=1,
        TargetName=TARGET,
        CredentialBlobSize=len(raw),
        CredentialBlob=blob,
        Persist=2,
        UserName=value.installation_id,
    )
    if not api.CredWriteW(ctypes.byref(record), 0):
        raise HTTPException(503, "Não foi possível salvar no cofre de credenciais do Windows.")


def configuration():
    # An environment origin selects the ENTIRE environment tuple, never mixes identities.
    if os.environ.get("THERMOPOWER_RESULTS_PORTAL_URL"):
        return {
            "url": os.environ["THERMOPOWER_RESULTS_PORTAL_URL"],
            "installation_id": os.environ.get("THERMOPOWER_RESULTS_PORTAL_INSTALLATION_ID", ""),
            "credential": os.environ.get("THERMOPOWER_RESULTS_PORTAL_PUBLISH_KEY", ""),
        }
    return read_vault()


def configuration_status():
    value = configuration()
    safe_url = ""
    try:
        validated = PortalConfiguration.model_validate(value)
        safe_url = validated.url
        configured = True
    except ValueError:
        configured = False
    return {
        "configured": configured,
        "url": safe_url,
        "installation_id": value.get("installation_id", ""),
        "managed_by_environment": bool(os.environ.get("THERMOPOWER_RESULTS_PORTAL_URL")),
    }
