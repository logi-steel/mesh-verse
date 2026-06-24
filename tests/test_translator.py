"""Hardware-free tests for Mesh Verse's public-only bridge rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_NAME = "meshverse_translator_under_test"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def install_dependency_stubs() -> None:
    meshtastic = ModuleType("meshtastic")
    serial_interface = ModuleType("meshtastic.serial_interface")

    class SerialInterface:  # pragma: no cover
        pass

    serial_interface.SerialInterface = SerialInterface
    meshtastic.serial_interface = serial_interface

    meshcore = ModuleType("meshcore")

    class EventType:
        ERROR = "ERROR"
        CHANNEL_MSG_RECV = "CHANNEL_MSG_RECV"

    class MeshCore:  # pragma: no cover
        pass

    meshcore.EventType = EventType
    meshcore.MeshCore = MeshCore

    pubsub = ModuleType("pubsub")

    class Pub:
        def subscribe(self, *_args, **_kwargs) -> None:
            return None

        def unsubscribe(self, *_args, **_kwargs) -> None:
            return None

    pubsub.pub = Pub()
    sys.modules["meshtastic"] = meshtastic
    sys.modules["meshtastic.serial_interface"] = serial_interface
    sys.modules["meshcore"] = meshcore
    sys.modules["pubsub"] = pubsub


def load_translator():
    install_dependency_stubs()
    spec = importlib.util.spec_from_file_location(MODULE_NAME, ROOT / "translator.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load translator.py for testing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


translator = load_translator()


def make_config(**overrides):
    values = {
        "meshtastic_port": "/dev/fake-meshtastic",
        "meshcore_port": "/dev/fake-meshcore",
        "meshtastic_channel": 0,
        "meshcore_channel": 0,
        "dedupe_seconds": 120,
        "max_text_chars": 180,
        "dry_run": False,
        "debug": False,
    }
    values.update(overrides)
    return translator.BridgeConfig(**values)


class TextHelpersTests(unittest.TestCase):
    def test_clean_text_normalises_and_limits(self) -> None:
        self.assertEqual(translator.clean_text(b"  hello\x00 world  ", 20), "hello world")
        self.assertEqual(translator.clean_text("abcd", 3), "ab…")
        self.assertIsNone(translator.clean_text("   ", 20))
        self.assertIsNone(translator.clean_text(123, 20))

    def test_broadcast_detection_never_guesses_private_messages(self) -> None:
        self.assertTrue(translator.is_broadcast("^all"))
        self.assertTrue(translator.is_broadcast("0xffffffff"))
        self.assertTrue(translator.is_broadcast(translator.BROADCAST_NODE_NUM))
        self.assertFalse(translator.is_broadcast("!12345678"))
        self.assertFalse(translator.is_broadcast(None))

    def test_duplicate_cache_tracks_destination_separately(self) -> None:
        cache = translator.DuplicateCache(ttl_seconds=60)
        cache.remember_sent_to("meshcore", "same message")
        self.assertTrue(cache.was_sent_to("meshcore", " same   message "))
        self.assertFalse(cache.was_sent_to("meshtastic", "same message"))

    def test_config_rejects_one_radio_used_twice_and_too_small_messages(self) -> None:
        with self.assertRaises(ValueError):
            translator.MeshVerseBridge(make_config(meshcore_port="/dev/fake-meshtastic"))
        with self.assertRaises(ValueError):
            translator.MeshVerseBridge(make_config(max_text_chars=31))


class PublicPacketFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = translator.MeshVerseBridge(make_config(dry_run=True))

    def test_accepts_expected_public_text_packet(self) -> None:
        packet = {
            "channel": 0,
            "to": "^all",
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "  hello mesh  "},
        }
        self.assertEqual(self.bridge._extract_meshtastic_public_text(packet), "hello mesh")

    def test_rejects_private_nontext_and_other_channel_packets(self) -> None:
        private_packet = {
            "channel": 0,
            "to": "!12345678",
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "do not relay"},
        }
        telemetry_packet = {
            "channel": 0,
            "to": "^all",
            "decoded": {"portnum": "TELEMETRY_APP", "text": "not text"},
        }
        other_channel_packet = {
            "channel": 1,
            "to": "^all",
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "wrong channel"},
        }
        self.assertIsNone(self.bridge._extract_meshtastic_public_text(private_packet))
        self.assertIsNone(self.bridge._extract_meshtastic_public_text(telemetry_packet))
        self.assertIsNone(self.bridge._extract_meshtastic_public_text(other_channel_packet))

    def test_relay_text_uses_stable_network_specific_alias(self) -> None:
        alias, message = self.bridge._relay_text("meshtastic", "!A1B2C3D4", "hello")
        self.assertTrue(alias.startswith("MT-"))
        self.assertEqual(message, f"[MV/{alias}] hello")
        meshcore_alias, _ = self.bridge._relay_text("meshcore", "a1b2c3d4", "hello")
        self.assertTrue(meshcore_alias.startswith("MC-"))
        self.assertNotEqual(alias, meshcore_alias)


class FakeMeshCoreCommands:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_chan_msg(self, channel: int, text: str) -> SimpleNamespace:
        self.sent.append((channel, text))
        return SimpleNamespace(type="OK", payload={})


class FakeMeshCoreRadio:
    def __init__(self) -> None:
        self.commands = FakeMeshCoreCommands()


class FakeMeshtasticRadio:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def sendText(self, text: str, **kwargs: object) -> None:
        self.sent.append({"text": text, **kwargs})


class RelayEmulationTests(unittest.IsolatedAsyncioTestCase):
    """Simulate two radios without opening a serial port or transmitting."""

    async def test_two_way_relay_and_local_echo_suppression(self) -> None:
        bridge = translator.MeshVerseBridge(make_config())
        bridge.meshcore = FakeMeshCoreRadio()
        bridge.meshtastic_iface = FakeMeshtasticRadio()
        bridge.aliases.aliases["meshtastic"]["!a1b2c3d4"] = "MT-ALFA"
        bridge.aliases.aliases["meshcore"]["cafe1234"] = "MC-BRAVO"

        await bridge._handle_meshtastic_packet(
            {
                "channel": 0,
                "to": "^all",
                "fromId": "!A1B2C3D4",
                "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "hej"},
            }
        )
        self.assertEqual(bridge.meshcore.commands.sent, [(0, "[MV/MT-ALFA] hej")])

        await bridge._on_meshcore_channel_message(
            SimpleNamespace(
                payload={
                    "channel_idx": 0,
                    "pubkey_prefix": "gateway",
                    "text": "[MV/MT-ALFA] hej",
                }
            )
        )
        self.assertEqual(bridge.meshtastic_iface.sent, [])
        self.assertEqual(bridge.stats.dropped_echoes, 1)

        await bridge._on_meshcore_channel_message(
            SimpleNamespace(
                payload={
                    "channel_idx": 0,
                    "pubkey_prefix": "CAFE1234",
                    "text": "siema",
                }
            )
        )
        self.assertEqual(
            bridge.meshtastic_iface.sent,
            [{
                "text": "[MV/MC-BRAVO] siema",
                "destinationId": "^all",
                "wantAck": False,
                "channelIndex": 0,
            }],
        )

    async def test_foreign_relay_envelope_is_not_bridged_again(self) -> None:
        bridge = translator.MeshVerseBridge(make_config())
        bridge.meshcore = FakeMeshCoreRadio()
        bridge.meshtastic_iface = FakeMeshtasticRadio()

        await bridge._handle_meshtastic_packet(
            {
                "channel": 0,
                "to": "^all",
                "fromId": "!other-gateway",
                "decoded": {
                    "portnum": "TEXT_MESSAGE_APP",
                    "text": "[MV/MT-OTHER] already relayed",
                },
            }
        )
        self.assertEqual(bridge.meshcore.commands.sent, [])
        self.assertEqual(bridge.stats.dropped_relay_envelopes, 1)


if __name__ == "__main__":
    unittest.main()
