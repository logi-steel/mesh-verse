"""Pseudonymous source aliases for Mesh Verse public relay messages.

Aliases are local display labels. They are not authentication and they do not
create direct-message routes between Meshtastic and MeshCore.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


NETWORK_PREFIXES = {
    "meshtastic": "MT",
    "meshcore": "MC",
}

_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,24}$")


class AliasConfigurationError(ValueError):
    """Raised when an alias JSON file is malformed or unsafe to use."""


@dataclass
class AliasRegistry:
    """Resolve stable, local aliases from network source identifiers."""

    aliases: dict[str, dict[str, str]] = field(
        default_factory=lambda: {network: {} for network in NETWORK_PREFIXES}
    )

    @classmethod
    def from_file(cls, path: str) -> "AliasRegistry":
        """Load optional aliases from a JSON file.

        Expected format::

            {
              "version": 1,
              "aliases": {
                "meshtastic": {"!a1b2c3d4": "MT-ALFA"},
                "meshcore": {"a1b2c3d4": "MC-BRAVO"}
              }
            }
        """
        source_path = Path(path)
        try:
            document = json.loads(source_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise AliasConfigurationError(
                f"Could not read alias file {source_path}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise AliasConfigurationError(
                f"Alias file {source_path} is not valid JSON: {exc.msg}"
            ) from exc

        if not isinstance(document, dict):
            raise AliasConfigurationError("Alias file must contain a JSON object.")

        version = document.get("version", 1)
        if version != 1:
            raise AliasConfigurationError(
                f"Unsupported alias file version {version!r}; expected 1."
            )

        raw_aliases = document.get("aliases", document)
        if not isinstance(raw_aliases, dict):
            raise AliasConfigurationError("'aliases' must be a JSON object.")

        registry = cls()
        for network in NETWORK_PREFIXES:
            entries = raw_aliases.get(network, {})
            if entries is None:
                continue
            if not isinstance(entries, dict):
                raise AliasConfigurationError(
                    f"aliases.{network} must be a JSON object."
                )

            for raw_source, raw_alias in entries.items():
                source = registry.normalise_source(raw_source)
                alias = registry.validate_alias(raw_alias)
                registry.aliases[network][source] = alias

        return registry

    @staticmethod
    def normalise_source(value: Any) -> str:
        source = str(value).strip().lower()
        if not source:
            raise AliasConfigurationError("Alias source identifiers cannot be empty.")
        return source

    @staticmethod
    def validate_alias(value: Any) -> str:
        if not isinstance(value, str):
            raise AliasConfigurationError("Every alias must be a string.")

        alias = value.strip()
        if not _ALIAS_PATTERN.fullmatch(alias):
            raise AliasConfigurationError(
                "Aliases must contain 1-24 ASCII letters, digits, '-' or '_'."
            )
        return alias

    def alias_for(self, network: str, source: Any) -> str:
        """Return an explicit alias or a deterministic privacy-preserving fallback."""
        if network not in NETWORK_PREFIXES:
            raise ValueError(f"Unknown Mesh Verse network: {network}")

        source_id = self.normalise_source(source)
        configured = self.aliases.get(network, {}).get(source_id)
        if configured is not None:
            return configured

        digest = hashlib.sha256(
            f"mesh-verse:{network}:{source_id}".encode("utf-8")
        ).hexdigest()[:6].upper()
        return f"{NETWORK_PREFIXES[network]}-{digest}"


def format_relay_text(alias: str, text: str, max_chars: int) -> str:
    """Prefix relayed public text with an alias without exceeding its size limit."""
    if max_chars < 2:
        raise ValueError("max_chars must be at least 2")

    safe_alias = AliasRegistry.validate_alias(alias)
    prefix = f"[{safe_alias}] "
    message = prefix + text
    if len(message) <= max_chars:
        return message

    remaining = max_chars - len(prefix)
    if remaining <= 0:
        return prefix[:max_chars]
    if remaining == 1:
        return prefix + "…"

    return prefix + text[: remaining - 1].rstrip() + "…"
