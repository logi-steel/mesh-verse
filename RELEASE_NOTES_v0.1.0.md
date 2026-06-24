# Mesh Verse v0.1.0: First Relay

Mesh Verse v0.1.0 is the first experimental release of a small host-side bridge for public text channels between Meshtastic and MeshCore.

## Included

- Meshtastic public channel to MeshCore public channel relay.
- Visible relay envelopes such as `[MV/MT-ALFA] hello`.
- Automatic stable aliases and optional local friendly aliases.
- Echo suppression and protection against relaying an already relayed Mesh Verse message again.
- `--check-config`, `--dry-run`, `--version`, tests, a deployment template, and setup documentation.

## Before using it

1. Use two separate USB radios: one Meshtastic radio and one MeshCore Companion radio.
2. Create a controlled public channel on each network.
3. Run `--check-config`.
4. Run `--dry-run` with short test messages from radios you control.
5. Remove `--dry-run` only after the logs match the intended channel mapping.

## Important limitations

This is experimental software. It copies public text only. It does not forward private messages, files, telemetry, positions, or raw radio packets. It does not verify who a person is, and an alias is not a verified identity.

A relayed message is copied, not moved: it stays visible on its original network and appears as a new public message on the other network.

## Compatibility

Mesh Verse runs on Python 3.10+ and is intended for a Raspberry Pi, Mac, or Linux host. The host needs two connected radios. This release was tested with simulated radio interfaces and CI, not with every physical radio and firmware combination.

## License

GNU GPL v3.
