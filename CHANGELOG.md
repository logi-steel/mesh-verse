# Changelog

All notable changes to Mesh Verse are documented here.

## [0.1.2] - 2026-06-25

### Added

- Optional `--status-file` JSON snapshot for local health checks, dashboards, and post-mortem debugging. The snapshot is written atomically and records the bridge state, active channel indices, dry-run mode, and relay counters.
- Optional `--max-relays-per-minute` per-direction rolling limit. It is disabled by default (`0`) so existing deployments keep their current behaviour.
- Counters for simulated dry-run relays, failed sends, and messages dropped by the rate limiter.
- Tests for the status snapshot, relay throttling, malformed packet handling, and send-error accounting.

### Fixed

- Meshtastic packets without an explicit channel index are now ignored instead of being treated as channel `0`.
- Malformed non-dictionary Meshtastic callback payloads are ignored safely.
- Exceptions or error replies during either send direction are logged and counted instead of escaping the message handler without diagnostic state.
- Unexpected top-level runtime failures now exit with a clear logged error and status code `1`.

### Operational notes

- Start with `--dry-run`. A useful first live limit is `--max-relays-per-minute 10`; tune it to the traffic and airtime budget of the two local channels.
- `--status-file` is local metadata only. It does not expose serial-device paths, message text, source IDs, or private traffic.

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
