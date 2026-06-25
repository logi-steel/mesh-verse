#!/usr/bin/env python3
"""Mesh Verse v0.1.2 public-channel Meshtastic <-> MeshCore bridge.

The bridge copies text from one selected public channel to another selected public
channel. It never forwards direct messages, telemetry, positions, files, binary
packets, or raw LoRa frames.

Run with --check-config and then --dry-run before enabling real transmission.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Optional

import meshtastic.serial_interface
from identity_aliases import (
    AliasConfigurationError,
    AliasRegistry,
    format_relay_text,
    is_relay_text,
)
from meshcore import EventType, MeshCore
from meshverse_version import __version__
from pubsub import pub

LOGGER = logging.getLogger("mesh_verse")
BROADCAST_NODE_NUM = 0xFFFFFFFF
MIN_RELAY_TEXT_CHARS = 32
STATUS_SCHEMA_VERSION = 1


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
    max_relays_per_minute: int = 0
    status_file: Optional[str] = None


@dataclass
class BridgeStats:
    """Small local counters printed on graceful shutdown and status snapshots."""

    forwarded_mt_to_mc: int = 0
    forwarded_mc_to_mt: int = 0
    simulated_mt_to_mc: int = 0
    simulated_mc_to_mt: int = 0
    failed_mt_to_mc: int = 0
    failed_mc_to_mt: int = 0
    dropped_echoes: int = 0
    dropped_relay_envelopes: int = 0
    dropped_rate_limited: int = 0


@dataclass
class DuplicateCache:
    """Remember recently forwarded text long enough to stop local echoes."""

    ttl_seconds: int
    _entries: dict[tuple[str, str], float] = field(default_factory=dict)

    @staticmethod
    def _digest(text: str) -> str:
        normalised = " ".join(text.strip().split())
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        stale = [key for key, timestamp in self._entries.items() if timestamp < cutoff]
        for key in stale:
            del self._entries[key]

    def was_sent_to(self, destination: str, text: str) -> bool:
        self._prune()
        return (destination, self._digest(text)) in self._entries

    def remember_sent_to(self, destination: str, text: str) -> None:
        self._prune()
        self._entries[(destination, self._digest(text))] = time.monotonic()


@dataclass
class RelayRateLimiter:
    """Optional per-direction rolling limiter for accidental bridge floods."""

    max_events: int
    window_seconds: int = 60
    _timestamps: dict[str, deque[float]] = field(default_factory=dict)

    def allow(self, direction: str) -> bool:
        if self.max_events == 0:
            return True

        now = time.monotonic()
        cutoff = now - self.window_seconds
        timestamps = self._timestamps.setdefault(direction, deque())
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        if len(timestamps) >= self.max_events:
            return False
        timestamps.append(now)
        return True


def validate_bridge_config(config: BridgeConfig) -> None:
    """Reject dangerous or impossible local configuration before opening serial."""
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
    if config.max_relays_per_minute < 0:
        raise ValueError("max_relays_per_minute cannot be negative.")
    if config.status_file is not None:
        target = Path(config.status_file).expanduser()
        if target.exists() and target.is_dir():
            raise ValueError("status_file must point to a file, not a directory.")
        if not target.parent.exists():
            raise ValueError(
                f"The status_file directory does not exist: {target.parent}"
            )


def is_text_port(portnum: Any) -> bool:
    """Accept numeric and enum/string representations used by Meshtastic."""
    return portnum == 1 or str(portnum).split(".")[-1] == "TEXT_MESSAGE_APP"


def is_broadcast(destination: Any) -> bool:
    """Return True only for public/broadcast Meshtastic packets."""
    if destination == BROADCAST_NODE_NUM or destination == -1:
        return True
    if isinstance(destination, str):
        return destination.strip().lower() in {
            "^all",
            "all",
            "broadcast",
            "0xffffffff",
            "!ffffffff",
            str(BROADCAST_NODE_NUM),
        }
    return False


def clean_text(value: Any, max_chars: int) -> Optional[str]:
    """Normalise text and apply a visible length limit before relaying."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return None

    text = value.replace("\x00", "").strip()
    if not text:
        return None
    if len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


def get_int_from_payload(payload: dict[str, Any], *names: str, default: int = -1) -> int:
    """Read an integer from compatible MeshCore event field names."""
    for name in names:
        if name not in payload:
            continue
        try:
            return int(payload[name])
        except (TypeError, ValueError):
            continue
    return default


class MeshVerseBridge:
    """A deliberately narrow, public-channel-only bridge."""

    def __init__(self, config: BridgeConfig) -> None:
        validate_bridge_config(config)
        self.config = config
        self.deduper = DuplicateCache(config.dedupe_seconds)
        self.rate_limiter = RelayRateLimiter(config.max_relays_per_minute)
        self.stats = BridgeStats()
        self.aliases = (
            AliasRegistry.from_file(config.alias_file)
            if config.alias_file is not None
            else AliasRegistry()
        )
        if config.alias_file is not None:
            LOGGER.info("Loaded local aliases from %s", config.alias_file)

        self.meshtastic_iface: Optional[Any] = None
        self.meshcore: Optional[MeshCore] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._meshtastic_callback: Optional[Any] = None
        self._meshcore_subscriptions: list[Any] = []
        self._closed = False
        self._status_state = "starting"

    def _write_status(self) -> None:
        """Persist a small atomic JSON snapshot when the operator requested one."""
        if self.config.status_file is None:
            return

        target = Path(self.config.status_file).expanduser()
        snapshot = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "version": __version__,
            "state": self._status_state,
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "dry_run": self.config.dry_run,
            "channels": {
                "meshtastic": self.config.meshtastic_channel,
                "meshcore": self.config.meshcore_channel,
            },
            "max_relays_per_minute": self.config.max_relays_per_minute,
            "stats": asdict(self.stats),
        }
        temporary = target.with_name(f".{target.name}.tmp")
        try:
            temporary.write_text(
                json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, target)
        except OSError as exc:
            LOGGER.warning("Could not write status file %s: %s", target, exc)

    def _allow_relay(self, direction: str) -> bool:
        if self.rate_limiter.allow(direction):
            return True
        self.stats.dropped_rate_limited += 1
        LOGGER.warning(
            "Dropped %s relay because the %d/minute per-direction limit was reached",
            direction,
            self.config.max_relays_per_minute,
        )
        self._write_status()
        return False

    async def connect(self) -> None:
        """Open both serial links and register incoming-message listeners."""
        self._loop = asyncio.get_running_loop()
        LOGGER.info("Connecting to Meshtastic on %s", self.config.meshtastic_port)
        self.meshtastic_iface = meshtastic.serial_interface.SerialInterface(
            devPath=self.config.meshtastic_port,
        )

        LOGGER.info("Connecting to MeshCore on %s", self.config.meshcore_port)
        self.meshcore = await MeshCore.create_serial(
            self.config.meshcore_port,
            debug=self.config.debug,
        )
        await self.meshcore.start_auto_message_fetching()

        self._setup_meshtastic_listener()
        self._setup_meshcore_listener()
        self._status_state = "online"
        self._write_status()
        LOGGER.info(
            "Bridge online: Meshtastic channel %d <-> MeshCore channel %d",
            self.config.meshtastic_channel,
            self.config.meshcore_channel,
        )

    def _setup_meshtastic_listener(self) -> None:
        self._meshtastic_callback = self._on_meshtastic_pubsub
        pub.subscribe(self._meshtastic_callback, "meshtastic.receive.text")
        LOGGER.info("Meshtastic public-text listener enabled")

    def _setup_meshcore_listener(self) -> None:
        if self.meshcore is None:
            raise RuntimeError("MeshCore is not connected")
        subscription = self.meshcore.subscribe(
            EventType.CHANNEL_MSG_RECV,
            self._on_meshcore_channel_message,
        )
        self._meshcore_subscriptions.append(subscription)
        LOGGER.info("MeshCore public-channel listener enabled")

    def _on_meshtastic_pubsub(self, packet: dict[str, Any], interface: Any = None) -> None:
        """Move a thread-based Meshtastic callback safely onto the async loop."""
        if self._loop is None or self._loop.is_closed() or self._closed:
            return
        future = asyncio.run_coroutine_threadsafe(
            self._handle_meshtastic_packet(packet), self._loop
        )
        future.add_done_callback(self._report_background_error)

    @staticmethod
    def _report_background_error(future: Any) -> None:
        try:
            future.result()
        except Exception:
            LOGGER.exception("Unhandled Meshtastic callback error")

    def _extract_meshtastic_public_text(self, packet: Any) -> Optional[str]:
        if not isinstance(packet, dict):
            LOGGER.debug("Ignoring Meshtastic event with unexpected packet: %r", packet)
            return None
        decoded = packet.get("decoded") or {}
        if not isinstance(decoded, dict) or not is_text_port(decoded.get("portnum")):
            return None
        if "channel" not in packet:
            LOGGER.debug("Ignoring Meshtastic text packet without a channel index")
            return None
        try:
            packet_channel = int(packet["channel"])
        except (TypeError, ValueError):
            return None
        if packet_channel != self.config.meshtastic_channel:
            return None
        if not is_broadcast(packet.get("to")):
            return None
        return clean_text(decoded.get("text"), self.config.max_text_chars)

    def _relay_text(self, network: str, source: Any, text: str) -> tuple[str, str]:
        alias = self.aliases.alias_for(network, source)
        return alias, format_relay_text(alias, text, self.config.max_text_chars)

    def _should_drop_incoming(self, destination: str, text: str, network: str) -> bool:
        if self.deduper.was_sent_to(destination, text):
            self.stats.dropped_echoes += 1
            LOGGER.debug("Dropped %s echo: %r", network, text)
            self._write_status()
            return True
        if is_relay_text(text):
            self.stats.dropped_relay_envelopes += 1
            LOGGER.debug("Dropped existing Mesh Verse relay envelope from %s: %r", network, text)
            self._write_status()
            return True
        return False

    async def _handle_meshtastic_packet(self, packet: dict[str, Any]) -> None:
        text = self._extract_meshtastic_public_text(packet)
        if text is None:
            return
        if self._should_drop_incoming("meshtastic", text, "Meshtastic"):
            return

        source = packet.get("fromId") or packet.get("from") or "unknown"
        alias, relayed_text = self._relay_text("meshtastic", source, text)
        LOGGER.info("Meshtastic -> MeshCore as %s: %s", alias, text)

        if not self.config.dry_run and self.meshcore is None:
            LOGGER.warning("MeshCore is disconnected; message was not forwarded")
            return
        if not self._allow_relay("mt_to_mc"):
            return
        if self.config.dry_run:
            LOGGER.info(
                "[dry-run] Would send to MeshCore channel %d: %s",
                self.config.meshcore_channel,
                relayed_text,
            )
            self.deduper.remember_sent_to("meshcore", relayed_text)
            self.stats.simulated_mt_to_mc += 1
            self._write_status()
            return

        try:
            result = await self.meshcore.commands.send_chan_msg(
                self.config.meshcore_channel,
                relayed_text,
            )
        except Exception:
            self.stats.failed_mt_to_mc += 1
            LOGGER.exception("Could not forward message to MeshCore")
            self._write_status()
            return
        if getattr(result, "type", None) == EventType.ERROR:
            self.stats.failed_mt_to_mc += 1
            LOGGER.error("MeshCore rejected message: %s", getattr(result, "payload", None))
            self._write_status()
            return
        self.deduper.remember_sent_to("meshcore", relayed_text)
        self.stats.forwarded_mt_to_mc += 1
        self._write_status()
        LOGGER.info("Forwarded to MeshCore successfully")

    async def _on_meshcore_channel_message(self, event: Any) -> None:
        """Handle the documented MeshCore CHANNEL_MSG_RECV event."""
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            LOGGER.debug("Ignoring MeshCore event with unexpected payload: %r", payload)
            return

        channel_index = get_int_from_payload(
            payload, "channel_idx", "channel", "chan", default=-1
        )
        if channel_index != self.config.meshcore_channel:
            return
        text = clean_text(payload.get("text"), self.config.max_text_chars)
        if text is None:
            return
        if self._should_drop_incoming("meshcore", text, "MeshCore"):
            return

        source = payload.get("pubkey_prefix", "unknown")
        alias, relayed_text = self._relay_text("meshcore", source, text)
        LOGGER.info("MeshCore -> Meshtastic as %s: %s", alias, text)

        if not self.config.dry_run and self.meshtastic_iface is None:
            LOGGER.warning("Meshtastic is disconnected; message was not forwarded")
            return
        if not self._allow_relay("mc_to_mt"):
            return
        if self.config.dry_run:
            LOGGER.info(
                "[dry-run] Would send to Meshtastic channel %d: %s",
                self.config.meshtastic_channel,
                relayed_text,
            )
            self.deduper.remember_sent_to("meshtastic", relayed_text)
            self.stats.simulated_mc_to_mt += 1
            self._write_status()
            return

        try:
            self.meshtastic_iface.sendText(
                relayed_text,
                destinationId="^all",
                wantAck=False,
                channelIndex=self.config.meshtastic_channel,
            )
        except Exception:
            self.stats.failed_mc_to_mt += 1
            LOGGER.exception("Could not forward message to Meshtastic")
            self._write_status()
            return
        self.deduper.remember_sent_to("meshtastic", relayed_text)
        self.stats.forwarded_mc_to_mt += 1
        self._write_status()
        LOGGER.info("Forwarded to Meshtastic successfully")

    async def close(self) -> None:
        """Unsubscribe and close hardware connections cleanly."""
        if self._closed:
            return
        self._closed = True

        if self._meshtastic_callback is not None:
            try:
                pub.unsubscribe(self._meshtastic_callback, "meshtastic.receive.text")
            except Exception:
                LOGGER.debug("Meshtastic callback was already unsubscribed")
        if self.meshcore is not None:
            for subscription in self._meshcore_subscriptions:
                try:
                    self.meshcore.unsubscribe(subscription)
                except Exception:
                    LOGGER.debug("MeshCore subscription was already removed")
            try:
                await self.meshcore.stop_auto_message_fetching()
            except Exception:
                LOGGER.debug("MeshCore auto-fetcher was already stopped")
            try:
                await self.meshcore.disconnect()
            except Exception:
                LOGGER.exception("MeshCore disconnect failed")
        if self.meshtastic_iface is not None:
            try:
                self.meshtastic_iface.close()
            except Exception:
                LOGGER.exception("Meshtastic disconnect failed")

        self._status_state = "closed"
        self._write_status()
        LOGGER.info(
            "Bridge closed | MT->MC=%d MC->MT=%d simulated=%d/%d failures=%d/%d "
            "echoes=%d relay-envelopes=%d rate-limited=%d",
            self.stats.forwarded_mt_to_mc,
            self.stats.forwarded_mc_to_mt,
            self.stats.simulated_mt_to_mc,
            self.stats.simulated_mc_to_mt,
            self.stats.failed_mt_to_mc,
            self.stats.failed_mc_to_mt,
            self.stats.dropped_echoes,
            self.stats.dropped_relay_envelopes,
            self.stats.dropped_rate_limited,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mesh Verse public-channel Meshtastic <-> MeshCore bridge.",
    )
    parser.add_argument("--version", action="version", version=f"Mesh Verse {__version__}")
    parser.add_argument(
        "--meshtastic-port",
        required=True,
        help="Serial device for the Meshtastic radio, e.g. /dev/ttyACM0",
    )
    parser.add_argument(
        "--meshcore-port",
        required=True,
        help="Serial device for the MeshCore companion, e.g. /dev/ttyUSB0",
    )
    parser.add_argument(
        "--meshtastic-channel",
        type=int,
        default=0,
        help="Public Meshtastic channel index to bridge (default: 0)",
    )
    parser.add_argument(
        "--meshcore-channel",
        type=int,
        default=0,
        help="Public MeshCore channel index to bridge (default: 0)",
    )
    parser.add_argument(
        "--dedupe-seconds",
        type=int,
        default=120,
        help="Seconds to remember forwarded text and suppress local echoes (default: 120)",
    )
    parser.add_argument(
        "--max-text-chars",
        type=int,
        default=180,
        help="Maximum relayed text length including the Mesh Verse envelope (default: 180)",
    )
    parser.add_argument(
        "--max-relays-per-minute",
        type=int,
        default=0,
        help="Maximum relays per direction in a rolling minute; 0 disables the limit (default: 0)",
    )
    parser.add_argument(
        "--status-file",
        help="Optional JSON status snapshot path, updated after bridge activity",
    )
    parser.add_argument(
        "--alias-file",
        help="Optional JSON source-ID to friendly-alias map; see bridge_aliases.example.json",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate arguments and the optional alias file without opening radios",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log forwarding decisions but never transmit anything",
    )
    parser.add_argument("--debug", action="store_true", help="Enable detailed logging")
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> BridgeConfig:
    return BridgeConfig(
        meshtastic_port=args.meshtastic_port,
        meshcore_port=args.meshcore_port,
        meshtastic_channel=args.meshtastic_channel,
        meshcore_channel=args.meshcore_channel,
        dedupe_seconds=args.dedupe_seconds,
        max_text_chars=args.max_text_chars,
        dry_run=args.dry_run,
        debug=args.debug,
        alias_file=args.alias_file,
        max_relays_per_minute=args.max_relays_per_minute,
        status_file=args.status_file,
    )


async def run_bridge(config: BridgeConfig) -> None:
    bridge = MeshVerseBridge(config)
    try:
        await bridge.connect()
        LOGGER.info("Listening. Stop with Ctrl+C.")
        while True:
            await asyncio.sleep(3600)
    finally:
        await bridge.close()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    try:
        config = build_config(args)
        check_bridge = MeshVerseBridge(config)
        if args.check_config:
            LOGGER.info(
                "Configuration valid for Meshtastic channel %d <-> MeshCore channel %d",
                config.meshtastic_channel,
                config.meshcore_channel,
            )
            return
        del check_bridge
        asyncio.run(run_bridge(config))
    except KeyboardInterrupt:
        LOGGER.info("Shutdown requested by user")
    except (AliasConfigurationError, ValueError) as exc:
        LOGGER.error("Configuration error: %s", exc)
        raise SystemExit(2) from exc
    except Exception:
        LOGGER.exception("Mesh Verse stopped because of an unexpected runtime error")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
