"""Hardware-free tests for Mesh Verse's public-only bridge rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_NAME = "meshverse_translator_under_test"


def install_dependency_stubs() -> None:
    """Provide the tiny import surface translator.py needs during unit tests."""

    meshtastic = ModuleType("meshtastic")
    serial_interface = ModuleType("meshtastic.serial_interface")

    class SerialInterface:  # pragma: no cover - only an import placeholder
        pass

    serial_interface.SerialInterface = SerialInterface
    meshtastic.serial_interface = serial_interface

    meshcore = ModuleType("meshcore")

    class EventType:
        ERROR = "ERROR"
        CHANNEL_MSG_RECV = "CHANNEL_MSG_RECV"

    class MeshCore:  # pragma: no cover - only an import placeholder
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


class PublicPacketFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        config = translator.BridgeConfig(
            meshtastic_port="/dev/ttyACM0",
            meshcore_port="/dev/ttyUSB0",
            meshtastic_channel=0,
            meshcore_channel=0,
            dedupe_seconds=120,
            max_text_chars=180,
            dry_run=True,
            debug=False,
        )
        self.bridge = translator.MeshVerseBridge(config)

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


if __name__ == "__main__":
    unittest.main()
