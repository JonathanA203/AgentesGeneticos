"""Mensajes de laboratorio entre padre e hijo (colas locales)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import time
from typing import Any, Literal

Kind = Literal[
    "heartbeat",
    "ack",
    "parent_ping",
    "parent_alive",
    "child_down",
    "recover",
    "recovered",
    "promote",
    "shutdown",
]


@dataclass
class Message:
    kind: Kind
    sender: str
    target: str
    ts: float = field(default_factory=time)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
