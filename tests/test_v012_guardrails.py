"""Focused tests for Mesh Verse v0.1.2 bridge guardrails."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from test_translator import FakeMeshCoreRadio, make_config, translator


class PacketSafetyTests(unittest.TestCase):
    def test_rejects_malformed_packets_and_missing_channel_metadata(self) -> None:
        bridge = translator.MeshVerseBridge(make_config())
        self.assertIsNone(bridge._extract_meshtastic_public_text(["not", "a", "packet"]))
        self.assertIsNone(
            bridge._extract_meshtastic_public_text(
                {
                    "to": "^all",
                    "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "unsafe"},
                }
            )
        )


class GuardrailUnitTests(unittest.TestCase):
    def test_rate_limiter_is_per_direction_and_opt_in(self) -> None:
        unlimited = translator.RelayRateLimiter(max_events=0)
        self.assertTrue(unlimited.allow("mt_to_mc"))
        self.assertTrue(unlimited.allow("mt_to_mc"))

        limited = translator.RelayRateLimiter(max_events=2)
        self.assertTrue(limited.allow("mt_to_mc"))
        self.assertTrue(limited.allow("mt_to_mc"))
        self.assertFalse(limited.allow("mt_to_mc"))
        self.assertTrue(limited.allow("mc_to_mt"))

    def test_rejects_negative_rate_limit_and_invalid_status_path(self) -> None:
        with self.assertRaises(ValueError):
            translator.MeshVerseBridge(make_config(max_relays_per_minute=-1))
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                translator.MeshVerseBridge(make_config(status_file=tmp))

    def test_status_snapshot_is_machine_readable_and_contains_counters(self) -> None:
        with TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "meshverse-status.json"
            bridge = translator.MeshVerseBridge(make_config(status_file=str(status_path)))
            bridge._status_state = "online"
            bridge.stats.forwarded_mt_to_mc = 3
            bridge.stats.dropped_rate_limited = 2
            bridge._write_status()

            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["version"], "0.1.3")
            self.assertEqual(payload["state"], "online")
            self.assertEqual(payload["stats"]["forwarded_mt_to_mc"], 3)
            self.assertEqual(payload["stats"]["dropped_rate_limited"], 2)
            self.assertIn("updated_at", payload)


class GuardrailRelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_stops_second_live_relay_and_tracks_drop(self) -> None:
        bridge = translator.MeshVerseBridge(make_config(max_relays_per_minute=1))
        bridge.meshcore = FakeMeshCoreRadio()

        await bridge._handle_meshtastic_packet(
            {
                "channel": 0,
                "to": "^all",
                "fromId": "!one",
                "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "first"},
            }
        )
        await bridge._handle_meshtastic_packet(
            {
                "channel": 0,
                "to": "^all",
                "fromId": "!two",
                "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "second"},
            }
        )

        self.assertEqual(len(bridge.meshcore.commands.sent), 1)
        self.assertEqual(bridge.stats.forwarded_mt_to_mc, 1)
        self.assertEqual(bridge.stats.dropped_rate_limited, 1)

    async def test_meshcore_send_exception_is_counted_without_crashing_handler(self) -> None:
        class FailingCommands:
            async def send_chan_msg(self, _channel: int, _text: str) -> SimpleNamespace:
                raise RuntimeError("serial disconnected")

        bridge = translator.MeshVerseBridge(make_config())
        bridge.meshcore = SimpleNamespace(commands=FailingCommands())

        await bridge._handle_meshtastic_packet(
            {
                "channel": 0,
                "to": "^all",
                "fromId": "!one",
                "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "hello"},
            }
        )

        self.assertEqual(bridge.stats.failed_mt_to_mc, 1)
        self.assertEqual(bridge.stats.forwarded_mt_to_mc, 0)


if __name__ == "__main__":
    unittest.main()
