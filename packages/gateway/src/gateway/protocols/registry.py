"""Protocol adapter registry - auto-detection and lookup."""

from fastapi import WebSocket

from gateway.protocols.base import ProtocolAdapter


class ProtocolRegistry:
    def __init__(self):
        self._adapters: list[ProtocolAdapter] = []

    def register(self, adapter: ProtocolAdapter):
        """Register a protocol adapter."""
        self._adapters.append(adapter)

    def get(self, name: str) -> ProtocolAdapter | None:
        """Get adapter by name."""
        for adapter in self._adapters:
            if adapter.name == name:
                return adapter
        return None

    async def detect(self, ws: WebSocket, initial_data: bytes | str) -> ProtocolAdapter | None:
        """Auto-detect protocol from initial frame.

        Returns a fresh adapter instance so per-connection state (e.g. audio
        format negotiated during handshake) is not shared across devices.
        """
        for adapter in self._adapters:
            if await adapter.detect(ws, initial_data):
                # Create a fresh instance of the same adapter class
                return adapter.__class__()
        return None

    @property
    def adapters(self) -> list[ProtocolAdapter]:
        return list(self._adapters)


# Global registry
registry = ProtocolRegistry()
