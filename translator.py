#!/usr/bin/env python3
"""
Mesh Verse MVP v2.1: public-channel Meshtastic <-> MeshCore bridge.

What this version does:
- forwards public text-channel messages in both directions;
- uses the high-level Python APIs of both projects;
- does NOT forward private/direct messages, position data, telemetry, files,
  binary packets, or raw LoRa frames;
- keeps a short duplicate cache to avoid simple bridge loops.

Run with --dry-run first. It prints what would be forwarded without transmitting.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import meshtastic.serial_interface
from meshcore import EventType, MeshCore
from pubsub import pub

LOGGER = logging.getLogger("mesh_verse")

# Meshtastic broadcast node number. Keeping it local avoids depending on an
# internal constant whose import path may move between library releases.
BROADCAST_NODE_NUM = 0xFFFFFFFF


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


@dataclass
class DuplicateCache:
    """Remember recently forwarded text long enough to stop obvious loops."""

    ttl_seconds: int
    _entries: dict[tuple[str, str], float] = field(default_factory=dict)

    @staticmethod
    def _digest(text: str) -> str:
        normalised = " ".join(text.strip().split())
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        stale = [
            key
            for key, timestamp in self._entries.items()
            if timestamp < cutoff
        ]
        for key in stale:
            del self._entries[key]

    def was_sent_to(self, destination: str, text: str) -> bool:
        self._prune()
        return (destination, self._digest(text)) in self._entries

    def remember_sent_to(self, destination: str, text: str) -> None:
        self._prune()
        self._entries[(destination, self._digest(text))] = time.monotonic()


def is_text_port(portnum: Any) -> bool:
    """Accept both numeric and enum/string representations used by Meshtastic."""
    if portnum == 1:
        return True
    return str(portnum).split(".")[-1] == "TEXT_MESSAGE_APP"


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
    """Normalise text and apply a visible, safe length limit."""
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
    """Get an int from possible MeshCore payload field names."""
    for name in names:
        if name not in payload:
            continue
        try:
            return int(payload[name])
        except (TypeError, ValueError):
            continue
    return default


class MeshVerseBridge:
    """
    A deliberately narrow bridge.

    Public channel text is the safe MVP. Direct messages need an explicit,
    user-managed Meshtastic-node <-> MeshCore-contact mapping and should not be
    guessed from unrelated node IDs or public-key prefixes.
    """

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.deduper = DuplicateCache(config.dedupe_seconds)

        self.meshtastic_iface: Optional[Any] = None
        self.meshcore: Optional[MeshCore] = None

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._meshtastic_callback: Optional[Any] = None
        self._meshcore_subscriptions: list[Any] = []
        self._closed = False

    async def connect(self) -> None:
        """Open both serial connections and register listeners."""
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

        # MeshCore queues incoming messages on the companion. This enables the
        # library's documented automatic fetching of those queued messages.
        await self.meshcore.start_auto_message_fetching()

        self._setup_meshtastic_listener()
        self._setup_meshcore_listener()

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

    def _on_meshtastic_pubsub(
        self,
        packet: dict[str, Any],
        interface: Any = None,
    ) -> None:
        """
        PubSub callbacks may arrive from a non-async thread, so hand work to
        the bridge event loop safely instead of calling asyncio.create_task().
        """
        if self._loop is None or self._loop.is_closed() or self._closed:
            return

        future = asyncio.run_coroutine_threadsafe(
            self._handle_meshtastic_packet(packet),
            self._loop,
        )
        future.add_done_callback(self._report_background_error)

    @staticmethod
    def _report_background_error(future: Any) -> None:
        try:
            future.result()
        except Exception:
            LOGGER.exception("Unhandled Meshtastic callback error")

    def _extract_meshtastic_public_text(
        self,
        packet: dict[str, Any],
    ) -> Optional[str]:
        decoded = packet.get("decoded") or {}

        if not is_text_port(decoded.get("portnum")):
            return None

        try:
            packet_channel = int(packet.get("channel", 0))
        except (TypeError, ValueError):
            return None

        if packet_channel != self.config.meshtastic_channel:
            return None

        # Do not leak DMs into another network. Missing/unknown destinations
        # are treated as private instead of making an optimistic guess.
        if not is_broadcast(packet.get("to")):
            return None

        return clean_text(decoded.get("text"), self.config.max_text_chars)

    async def _handle_meshtastic_packet(self, packet: dict[str, Any]) -> None:
        text = self._extract_meshtastic_public_text(packet)
        if text is None:
            return

        # FIX: If this same text was recently sent *to Meshtastic* by the
        # bridge, a Meshtastic receive event may be our own echo. Drop it.
        if self.deduper.was_sent_to("meshtastic", text):
            LOGGER.debug("Dropped Meshtastic echo: %r", text)
            return

        source = packet.get("fromId") or packet.get("from") or "unknown"
        LOGGER.info("Meshtastic -> MeshCore from %s: %s", source, text)

        if self.config.dry_run:
            LOGGER.info(
                "[dry-run] Would send to MeshCore channel %d",
                self.config.meshcore_channel,
            )
            self.deduper.remember_sent_to("meshcore", text)
            return

        if self.meshcore is None:
            LOGGER.warning("MeshCore is disconnected; message was not forwarded")
            return

        result = await self.meshcore.commands.send_chan_msg(
            self.config.meshcore_channel,
            text,
        )
        if result.type == EventType.ERROR:
            LOGGER.error("MeshCore rejected message: %s", result.payload)
            return

        self.deduper.remember_sent_to("meshcore", text)
        LOGGER.info("Forwarded to MeshCore successfully")

    async def _on_meshcore_channel_message(self, event: Any) -> None:
        """Handle the documented MeshCore CHANNEL_MSG_RECV event."""
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            LOGGER.debug("Ignoring MeshCore event with unexpected payload: %r", payload)
            return

        channel_index = get_int_from_payload(
            payload,
            "channel_idx",
            "channel",
            "chan",
            default=-1,
        )
        if channel_index != self.config.meshcore_channel:
            return

        text = clean_text(payload.get("text"), self.config.max_text_chars)
        if text is None:
            return

        # FIX: If this same text was recently sent *to MeshCore* by the bridge,
        # a MeshCore channel event may be our own echo. Drop it.
        if self.deduper.was_sent_to("meshcore", text):
            LOGGER.debug("Dropped MeshCore echo: %r", text)
            return

        source = payload.get("pubkey_prefix", "unknown")
        LOGGER.info("MeshCore -> Meshtastic from %s: %s", source, text)

        if self.config.dry_run:
            LOGGER.info(
                "[dry-run] Would send to Meshtastic channel %d",
                self.config.meshtastic_channel,
            )
            self.deduper.remember_sent_to("meshtastic", text)
            return

        if self.meshtastic_iface is None:
            LOGGER.warning("Meshtastic is disconnected; message was not forwarded")
            return

        # Broadcast only. Public channel traffic must not silently become a DM.
        self.meshtastic_iface.sendText(
            text,
            destinationId="^all",
            wantAck=False,
            channelIndex=self.config.meshtastic_channel,
        )

        self.deduper.remember_sent_to("meshtastic", text)
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

        LOGGER.info("Bridge closed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mesh Verse public-channel Meshtastic <-> MeshCore bridge.",
    )
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
        help="Seconds to remember forwarded text and suppress loop echoes (default: 120)",
    )
    parser.add_argument(
        "--max-text-chars",
        type=int,
        default=180,
        help="Maximum forwarded text length; longer messages are visibly truncated (default: 180)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log forwarding decisions but never transmit anything",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable detailed library logging",
    )

    args = parser.parse_args()

    if args.meshtastic_channel < 0 or args.meshcore_channel < 0:
        parser.error("Channel indices cannot be negative.")
    if args.dedupe_seconds < 1:
        parser.error("--dedupe-seconds must be at least 1.")
    if args.max_text_chars < 2:
        parser.error("--max-text-chars must be at least 2.")

    return args


async def run_bridge(args: argparse.Namespace) -> None:
    config = BridgeConfig(
        meshtastic_port=args.meshtastic_port,
        meshcore_port=args.meshcore_port,
        meshtastic_channel=args.meshtastic_channel,
        meshcore_channel=args.meshcore_channel,
        dedupe_seconds=args.dedupe_seconds,
        max_text_chars=args.max_text_chars,
        dry_run=args.dry_run,
        debug=args.debug,
    )
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
        asyncio.run(run_bridge(args))
    except KeyboardInterrupt:
        LOGGER.info("Shutdown requested by user")


if __name__ == "__main__":
    main()
