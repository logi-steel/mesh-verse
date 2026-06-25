# Local status snapshot

Mesh Verse v0.1.2 can write a small local JSON file with its operating state and counters.

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --meshtastic-channel 1 \
  --meshcore-channel 1 \
  --max-relays-per-minute 10 \
  --status-file /var/lib/mesh-verse/status.json \
  --dry-run --debug
```

`--max-relays-per-minute` applies separately to each direction. `10` therefore permits up to ten Meshtastic → MeshCore relays and up to ten MeshCore → Meshtastic relays during the same rolling minute. Use `0`, the default, to disable the limiter.

The file is replaced atomically, so a dashboard or health-check script should never read a half-written JSON document.

Example:

```json
{
  "channels": {
    "meshcore": 1,
    "meshtastic": 1
  },
  "dry_run": true,
  "max_relays_per_minute": 10,
  "schema_version": 1,
  "state": "online",
  "stats": {
    "dropped_echoes": 0,
    "dropped_rate_limited": 0,
    "failed_mc_to_mt": 0,
    "failed_mt_to_mc": 0,
    "forwarded_mc_to_mt": 0,
    "forwarded_mt_to_mc": 0,
    "simulated_mc_to_mt": 2,
    "simulated_mt_to_mc": 4
  },
  "updated_at": "2026-06-25T10:15:00Z",
  "version": "0.1.2"
}
```

The snapshot intentionally excludes serial-device paths, source identifiers, aliases, and message text. It is a local diagnostic aid, not an internet-facing monitoring API.
