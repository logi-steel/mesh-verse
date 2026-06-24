# Changelog

All notable changes to Mesh Verse are documented here.

## [0.1.0] - 2026-06-24

### Added

- First public, experimental release of the Meshtastic ↔ MeshCore public-channel bridge.
- Stable local aliases for relayed sources, with optional friendly alias mapping.
- Visible relay envelopes such as `[MV/MT-ALFA]` and `[MV/MC-BRAVO]`.
- `--version` and `--check-config` command-line options.
- Local forwarding counters printed on graceful shutdown.
- Automated fake-radio tests for both relay directions, echo suppression, foreign-relay suppression, alias handling, and configuration checks.
- Setup, alias, deployment, and release documentation.

### Changed

- Forwarded messages now use a Mesh Verse relay envelope instead of a bare alias.
- Existing Mesh Verse envelopes are not relayed again, reducing the risk of loops when multiple bridge hosts exist.
- Configuration now rejects one serial device being supplied as both radio endpoints and rejects an unusably small text limit.

### Known limitations

- Experimental software: automated tests pass, but every hardware/firmware combination still needs a controlled dry-run.
- No private/direct messages, identity verification, file forwarding, telemetry forwarding, or automatic radio reconnection.
- A single bridge maps one selected Meshtastic public channel to one selected MeshCore public channel.
