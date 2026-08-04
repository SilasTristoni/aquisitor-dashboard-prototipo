"""Hardware-specific adapter boundaries.

No SCPI command is embedded here until it can be verified against the supplied manuals.
The explicit failure prevents a generic serial parser from being mistaken for homologated hardware.
"""

from app.adapters.serial import SerialJsonAdapter


class _PendingProtocolAdapter(SerialJsonAdapter):
    equipment: str

    async def connect(self) -> None:
        raise RuntimeError(
            f"{self.equipment}: comunicação física aguarda manual e homologação; "
            "nenhum comando foi inferido"
        )

    def parse_message(self, raw: bytes | str):
        del raw
        raise RuntimeError(f"Layout de mensagem do {self.equipment} ainda não homologado")


class At4532Adapter(_PendingProtocolAdapter):
    equipment = "Applent AT4532"


class Gpm8213Adapter(_PendingProtocolAdapter):
    equipment = "GW Instek GPM-8213"
