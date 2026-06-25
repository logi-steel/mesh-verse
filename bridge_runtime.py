"""Runtime bridge between Meshtastic and MeshCore public channels."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import meshtastic.serial_interface
from identity_aliases import (
    AliasRegistry,
    format_relay_text,
    is_relay_text,
)
from meshcore import EventType, MeshCore
from pubsub import pub

from bridge_safety import (
    BridgeConfig,
    BridgeStats,
    DuplicateCache,
    RelayRateLimiter,
    clean_text,
    get_int_from_payload,
    is_broadcast,
    is_text_port,
    validate_bridge_config,
)

LOGGER = logging.getLogger("mesh_verse")


class MeshVerseBridge:
    """A narrow, consent-based bridge for public text channels only."""

    def __init__(self, config: BridgeConfig) -> None:
        validate_bridge_config(config)
        self.config = config
        self.deduper = DuplicateCache(config.dedupe_seconds)
        self.rate_limiter = RelayRateLimiter(
            config.max_relays_per_minute,
            config.max_relays_per_source_per_minute,
        )
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
        self._radio_send_lock = asyncio.Lock()
        self._closed = False

    async def connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        LOGGER.info("Connecting to Meshtastic on %s", self.config.meshtastic_port)
        self.meshtastic_iface = meshtastic.serial_interface.SerialInterface(
            devPath=self.config.meshtastic_port
        )

        LOGGER.info("Connecting to MeshCore on %s", self.config.meshcore_port)
        self.meshcore = await MeshCore.create_serial(
            self.config.meshcore_port, debug=self.config.debug
        )
        await self.meshcore.start_auto_message_fetching()

        self._meshtastic_callback = self._on_meshtastic_pubsub
        pub.subscribe(self._meshtastic_callback, "meshtastic.receive.text")

        subscription = self.meshcore.subscribe(
            EventType.CHANNEL_MSG_RECV, self._on_meshcore_channel_message
        )
        self._meshcore_subscriptions.append(subscription)

        LOGGER.info(
            "Bridge online: Meshtastic channel %d <-> MeshCore channel %d "
            "(limit: %d/min per direction, %d/min per source)",
            self.config.meshtastic_channel,
            self.config.meshcore_channel,
            self.config.max_relays_per_minute,
            self.config.max_relays_per_source_per_minute,
        )

    def _on_meshtastic_pubsub(self, packet: dict[str, Any], interface: Any = None) -> None:
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

    def _extract_meshtastic_public_text(self, packet: dict[str, Any]) -> Optional[str]:
        decoded = packet.get("decoded") or {}
        if not is_text_port(decoded.get("portnum")):
            return None
        try:
            channel = int(packet.get("channel", 0))
        except (TypeError, ValueError):
            return None
        if channel != self.config.meshtastic_channel or not is_broadcast(packet.get("to")):
            return None
        return clean_text(decoded.get("text"), self.config.max_text_chars)

    def _relay_text(self, network: str, source: Any, text: str) -> tuple[str, str]:
        alias = self.aliases.alias_for(network, source)
        return alias, format_relay_text(alias, text, self.config.max_text_chars)

    def _should_drop_incoming(self, destination: str, text: str, network: str) -> bool:
        if self.deduper.was_sent_to(destination, text):
            self.stats.dropped_echoes += 1
            LOGGER.debug("Dropped %s echo: %r", network, text)
            return True
        if is_relay_text(text):
            self.stats.dropped_relay_envelopes += 1
            LOGGER.debug("Dropped existing Mesh Verse relay envelope from %s: %r", network, text)
            return True
        return False

    def _allow_relay(self, direction: str, source: Any) -> bool:
        reason = self.rate_limiter.allow(direction, source)
        if reason is None:
            return True
        self.stats.dropped_rate_limited += 1
        LOGGER.warning(
            "Dropped %s relay from %s because of %s (dropped=%d)",
            direction,
            self.rate_limiter.source_key(source),
            reason,
            self.stats.dropped_rate_limited,
        )
        return False

    async def _handle_meshtastic_packet(self, packet: dict[str, Any]) -> None:
        text = self._extract_meshtastic_public_text(packet)
        if text is None or self._should_drop_incoming("meshtastic", text, "Meshtastic"):
            return

        source = packet.get("fromId") or packet.get("from") or "unknown"
        if not self._allow_relay("mt-to-mc", source):
            return

        alias, relayed_text = self._relay_text("meshtastic", source, text)
        LOGGER.info("Meshtastic -> MeshCore as %s: %s", alias, text)

        if self.config.dry_run:
            LOGGER.info(
                "[dry-run] Would send to MeshCore channel %d: %s",
                self.config.meshcore_channel,
                relayed_text,
            )
            self.deduper.remember_sent_to("meshcore", relayed_text)
            return
        if self.meshcore is None:
            LOGGER.warning("MeshCore is disconnected; message was not forwarded")
            return

        async with self._radio_send_lock:
            result = await self.meshcore.commands.send_chan_msg(
                self.config.meshcore_channel, relayed_text
            )
        if result.type == EventType.ERROR:
            LOGGER.error("MeshCore rejected message: %s", result.payload)
            return
        self.deduper.remember_sent_to("meshcore", relayed_text)
        self.stats.forwarded_mt_to_mc += 1
        LOGGER.info("Forwarded to MeshCore successfully")

    async def _on_meshcore_channel_message(self, event: Any) -> None:
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            LOGGER.debug("Ignoring MeshCore event with unexpected payload: %r", payload)
            return

        channel = get_int_from_payload(payload, "channel_idx", "channel", "chan", default=-1)
        if channel != self.config.meshcore_channel:
            return
        text = clean_text(payload.get("text"), self.config.max_text_chars)
        if text is None or self._should_drop_incoming("meshcore", text, "MeshCore"):
            return

        source = payload.get("pubkey_prefix", "unknown")
        if not self._allow_relay("mc-to-mt", source):
            return

        alias, relayed_text = self._relay_text("meshcore", source, text)
        LOGGER.info("MeshCore -> Meshtastic as %s: %s", alias, text)

        if self.config.dry_run:
            LOGGER.info(
                "[dry-run] Would send to Meshtastic channel %d: %s",
                self.config.meshtastic_channel,
                relayed_text,
            )
            self.deduper.remember_sent_to("meshtastic", relayed_text)
            return
        if self.meshtastic_iface is None:
            LOGGER.warning("Meshtastic is disconnected; message was not forwarded")
            return

        async with self._radio_send_lock:
            self.meshtastic_iface.sendText(
                relayed_text,
                destinationId="^all",
                wantAck=False,
                channelIndex=self.config.meshtastic_channel,
            )
        self.deduper.remember_sent_to("meshtastic", relayed_text)
        self.stats.forwarded_mc_to_mt += 1
        LOGGER.info("Forwarded to Meshtastic successfully")

    async def close(self) -> None:
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

        LOGGER.info(
            "Bridge closed | MT->MC=%d MC->MT=%d echoes=%d relay-envelopes=%d "
            "rate-limited=%d",
            self.stats.forwarded_mt_to_mc,
            self.stats.forwarded_mc_to_mt,
            self.stats.dropped_echoes,
            self.stats.dropped_relay_envelopes,
            self.stats.dropped_rate_limited,
        )
