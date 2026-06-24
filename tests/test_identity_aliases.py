"""Tests for Mesh Verse's local pseudonymous alias layer."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from identity_aliases import (  # noqa: E402
    AliasConfigurationError,
    AliasRegistry,
    format_relay_text,
    is_relay_text,
)


class AliasRegistryTests(unittest.TestCase):
    def test_fallback_aliases_are_stable_and_network_specific(self) -> None:
        registry = AliasRegistry()
        first = registry.alias_for("meshtastic", "!A1B2C3D4")
        second = registry.alias_for("meshtastic", "!a1b2c3d4")
        meshcore = registry.alias_for("meshcore", "a1b2c3d4")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("MT-"))
        self.assertTrue(meshcore.startswith("MC-"))
        self.assertNotEqual(first, meshcore)

    def test_file_alias_overrides_fallback_without_storing_display_names(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "aliases.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "aliases": {
                            "meshtastic": {"!a1b2c3d4": "MT-ALFA"},
                            "meshcore": {"b2c3d4e5": "MC-BRAVO"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            registry = AliasRegistry.from_file(str(path))
        self.assertEqual(registry.alias_for("meshtastic", "!A1B2C3D4"), "MT-ALFA")
        self.assertEqual(registry.alias_for("meshcore", "b2c3d4e5"), "MC-BRAVO")

    def test_invalid_aliases_are_rejected(self) -> None:
        with self.assertRaises(AliasConfigurationError):
            AliasRegistry.validate_alias("space not allowed")
        with self.assertRaises(AliasConfigurationError):
            AliasRegistry.validate_alias("x" * 25)


class RelayTextTests(unittest.TestCase):
    def test_envelope_prefixes_and_truncates_within_limit(self) -> None:
        self.assertEqual(format_relay_text("MT-ALFA", "hello", 32), "[MV/MT-ALFA] hello")
        self.assertEqual(format_relay_text("MT-ALFA", "abcdefghij", 18), "[MV/MT-ALFA] abc…")

    def test_relay_envelope_detection_is_explicit(self) -> None:
        self.assertTrue(is_relay_text("[MV/MT-ALFA] hello"))
        self.assertTrue(is_relay_text("  [MV/MC-BRAVO] hello"))
        self.assertFalse(is_relay_text("[MT-ALFA] hello"))
        self.assertFalse(is_relay_text("ordinary text"))


if __name__ == "__main__":
    unittest.main()
