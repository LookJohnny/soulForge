"""Abstract protocol adapter interface.

This is the core abstraction that makes the gateway hardware-agnostic.
Each adapter translates between a specific wire protocol (e.g., xiaozhi
WebSocket binary frames) and SoulForge's internal normalized message format.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fastapi import WebSocket


class MessageType(Enum):
    AUDIO = "audio"
    TEXT = "text"
    CONTROL = "control"
    AUTH = "auth"
    HEARTBEAT = "heartbeat"
    TOUCH = "touch"


@dataclass
class InboundMessage:
    """Normalized message from device, protocol-agnostic."""

    type: MessageType
    device_id: str
    payload: bytes | dict | str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """Normalized message to device, protocol-agnostic."""

    type: MessageType
    payload: bytes | dict | str
    metadata: dict[str, Any] = field(default_factory=dict)


class ProtocolAdapter(ABC):
    """Abstract base for hardware protocol adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this protocol."""
        ...

    @abstractmethod
    async def detect(self, ws: WebSocket, initial_data: bytes | str) -> bool:
        """Return True if this adapter can handle the given initial frame."""
        ...

    @abstractmethod
    async def handshake(self, ws: WebSocket, initial_data: bytes | str) -> str:
        """Handle protocol-specific handshake, return device_id."""
        ...

    @abstractmethod
    async def decode(self, raw_data: bytes | str) -> InboundMessage:
        """Decode raw WebSocket frame into normalized InboundMessage."""
        ...

    @abstractmethod
    async def encode(self, message: OutboundMessage) -> bytes | str:
        """Encode normalized OutboundMessage into wire protocol frame."""
        ...
