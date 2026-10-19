"""Print only an installation registration hash; never print the machine credential."""

import argparse
import getpass
import hashlib
import json
import re


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--installation", required=True)
    args = parser.parse_args()
    if not all(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value)
               for value in (args.tenant, args.installation)):
        parser.error("Use IDs alfanuméricos com hífen/sublinhado, até 64 caracteres.")
    secret = getpass.getpass("Credencial aleatória da instalação (entrada oculta): ")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{32,256}", secret):
        parser.error("Credencial inválida: use 32 bytes aleatórios codificados em base64url.")
    print(json.dumps({args.installation: {
        "tenant_id": args.tenant,
        "credential_sha256": hashlib.sha256(secret.encode()).hexdigest(),
        "enabled": True,
    }}))


if __name__ == "__main__":
    main()
