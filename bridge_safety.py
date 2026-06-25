"""Small, hardware-free safety rules for Mesh Verse relays."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import hashlib
import os
import time
from typing import Any, Optional

BROADCAST_NODE_NUM = 0xFFFFFFFF
MIN_RELAY_TEXT_CHARS = 32
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_RATE_LIMIT_SOURCES = 512


@dataclass(frozen=True)
class BridgeConfig:
    meshtastic_port: str
    meshcore_port: str
    meshtastic_channel: int
    meshcore_channel: int
    dedupe_seconds: int
    max_text_chars: int
    dry_run: bool
    debug: bool
    alias_file: Optional[str] = None
    accept_cross_network_relay: bool = False
    max_relays_per_minute: int = 6
    max_relays_per_source_per_minute: int = 3


@dataclass
class BridgeStats:
    forwarded_mt_to_mc: int = 0
    forwarded_mc_to_mt: int = 0
    dropped_echoes: int = 0
    dropped_relay_envelopes: int = 0
    dropped_rate_limited: int = 0


@dataclass
class DuplicateCache:
    """Small, bounded echo cache for recently relayed text."""

    ttl_seconds: int
    max_entries: int = 1024
    _entries: dict[tuple[str, str], float] = field(default_factory=dict)

    @staticmethod
    def _digest(text: str) -> str:
        normalised = " ".join(text.strip().split())
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        for key, timestamp in list(self._entries.items()):
            if timestamp < cutoff:
                del self._entries[key]

        while len(self._entries) > self.max_entries:
            oldest = min(self._entries, key=self._entries.get)
            del self._entries[oldest]

    def was_sent_to(self, destination: str, text: str) -> bool:
        self._prune()
        return (destination, self._digest(text)) in self._entries

    def remember_sent_to(self, destination: str, text: str) -> None:
        self._prune()
        if len(self._entries) >= self.max_entries:
            oldest = min(self._entries, key=self._entries.get)
            del self._entries[oldest]
        self._entries[(destination, self._digest(text))] = time.monotonic()


@dataclass
class RelayRateLimiter:
    """Per-direction and per-source rolling limits for radio transmissions."""

    max_relays_per_minute: int
    max_relays_per_source_per_minute: int
    window_seconds: int = RATE_LIMIT_WINDOW_SECONDS
    max_sources: int = MAX_RATE_LIMIT_SOURCES
    _direction_events: dict[str, deque[float]] = field(default_factory=dict)
    _source_events: dict[tuple[str, str], deque[float]] = field(default_factory=dict)

    @staticmethod
    def source_key(source: Any) -> str:
        value = str(source).strip().lower()
        return value or "unknown"

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for bucket, events in list(self._direction_events.items()):
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                del self._direction_events[bucket]
        for bucket, events in list(self._source_events.items()):
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                del self._source_events[bucket]

    def allow(self, direction: str, source: Any) -> Optional[str]:
        now = time.monotonic()
        self._prune(now)

        direction_events = self._direction_events.setdefault(direction, deque())
        if len(direction_events) >= self.max_relays_per_minute:
            return "bridge-limit"

        source_bucket = (direction, self.source_key(source))
        source_events = self._source_events.get(source_bucket)
        if source_events is None:
            if len(self._source_events) >= self.max_sources:
                return "source-table-full"
            source_events = deque()
            self._source_events[source_bucket] = source_events

        if len(source_events) >= self.max_relays_per_source_per_minute:
            return "source-limit"

        direction_events.append(now)
        source_events.append(now)
        return None


def validate_bridge_config(config: BridgeConfig) -> None:
    if not config.meshtastic_port.strip() or not config.meshcore_port.strip():
        raise ValueError("Both USB serial paths are required.")
    if os.path.realpath(config.meshtastic_port) == os.path.realpath(config.meshcore_port):
        raise ValueError("Meshtastic and MeshCore must use two different serial devices.")
    if config.meshtastic_channel < 0 or config.meshcore_channel < 0:
        raise ValueError("Channel indices cannot be negative.")
    if config.dedupe_seconds < 1:
        raise ValueError("dedupe_seconds must be at least 1.")
    if config.max_text_chars < MIN_RELAY_TEXT_CHARS:
        raise ValueError(
            f"max_text_chars must be at least {MIN_RELAY_TEXT_CHARS} so relay labels fit."
        )
    if not config.accept_cross_network_relay:
        raise ValueError(
            "Refusing to bridge until --accept-cross-network-relay confirms that "
            "everyone using both selected channels knows messages will cross networks."
        )
    if config.max_relays_per_minute < 1:
        raise ValueError("max_relays_per_minute must be at least 1.")
    if config.max_relays_per_source_per_minute < 1:
        raise ValueError("max_relays_per_source_per_minute must be at least 1.")
    if config.max_relays_per_source_per_minute > config.max_relays_per_minute:
        raise ValueError(
            "max_relays_per_source_per_minute cannot exceed max_relays_per_minute."
        )


def is_text_port(portnum: Any) -> bool:
    return portnum == 1 or str(portnum).split(".")[-1] == "TEXT_MESSAGE_APP"


def is_broadcast(destination: Any) -> bool:
    if destination == BROADCAST_NODE_NUM or destination == -1:
        return True
    if isinstance(destination, str):
        return destination.strip().lower() in {
            "^all", "all", "broadcast", "0xffffffff", "!ffffffff",
            str(BROADCAST_NODE_NUM),
        }
    return False


def clean_text(value: Any, max_chars: int) -> Optional[str]:
    """Remove terminal controls, normalise whitespace, and apply a visible limit."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return None

    safe = "".join(
        " " if character.isspace() else character
        for character in value
        if character.isprintable() or character.isspace()
    )
    text = " ".join(safe.split())
    if not text:
        return None
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def get_int_from_payload(payload: dict[str, Any], *names: str, default: int = -1) -> int:
    for name in names:
        try:
            return int(payload[name])
        except (KeyError, TypeError, ValueError):
            continue
    return default
