# Mesh Verse

> **Status: experimental MVP.** Mesh Verse is currently an AI-assisted prototype maintained by the repository owner. It is not hardware-tested or production-ready yet, so use it first with `--dry-run` and only on radios you control.

Mesh Verse is a deliberately narrow bridge between a **Meshtastic public text channel** and a **MeshCore public text channel**.

**New to the project?** Start with the [First Real Setup guide](docs/SETUP.md). It explains the required two-radio architecture, controlled testing, and MacBook/Raspberry Pi setup. For display aliases, read [Alias guide](docs/ALIASES.md).

## What it does

- forwards public text-channel messages in both directions;
- prefixes relayed text with a stable local alias such as `[MT-ALFA]` or `[MC-BRAVO]` instead of forwarding an original display name;
- keeps a short duplicate cache to reduce simple bridge loops;
- lets you choose a channel index on each side;
- has a dry-run mode that logs decisions without transmitting;
- includes `meshverse-doctor`, a read-only serial-port preflight helper.

## What it does not do

- direct/private messages;
- position data, telemetry, files, binary packets, or raw LoRa frames;
- automatic contact matching or direct-message routing between networks;
- radio configuration, firmware flashing, or frequency changes;
- identity verification. A relay alias is a label, not proof of who typed a message.

That limitation is intentional. A bridge should not quietly turn private traffic into public traffic because someone thought “it will probably be fine.” Humanity already has enough of those decisions.

## Requirements

- Python **3.10+**;
- one Meshtastic radio reachable over USB serial;
- one MeshCore companion reachable over USB serial;
- a public channel configured on both systems;
- Go **1.20+** only if you want to build or run `meshverse-doctor`.

Use hardware, channels, and radio settings that comply with the rules where you operate.

## Install

```bash
git clone https://github.com/logi-steel/mesh-verse.git
cd mesh-verse
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Windows, activate the virtual environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Check the serial paths first

`meshverse-doctor` never opens, writes to, configures, or resets a radio. It only checks paths and prints a safe dry-run command.

```bash
go run ./tools/meshverse-doctor \
  --meshtastic-port /dev/ttyACM0 \
  --meshcore-port /dev/ttyUSB0
```

For a machine-readable report:

```bash
go run ./tools/meshverse-doctor --json
```

On Linux, prefer a stable `/dev/serial/by-id/...` path when possible. `/dev/ttyACM0` and `/dev/ttyUSB0` can swap after a reboot, because computers apparently enjoy assigning names by vibes.

## First bridge run: dry-run

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --meshtastic-channel 0 \
  --meshcore-channel 0 \
  --dry-run \
  --debug
```

Dry-run prints what the bridge would forward but never sends a packet. Confirm that only the expected public-channel text is detected before using the real bridge.

## Pseudonymous relay aliases

Without an alias file, Mesh Verse derives deterministic aliases from the sender's local network identifier, for example `[MT-8F12AB]` or `[MC-90CDEF]`. The same source keeps the same fallback alias after a restart.

To choose friendlier local labels, create an ignored local config file from the example:

```bash
cp bridge_aliases.example.json bridge_aliases.json
```

Edit only the local `bridge_aliases.json`, then add it to the bridge command:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --alias-file bridge_aliases.json \
  --dry-run \
  --debug
```

The alias map uses source identifiers, not human display names. It controls what label crosses the bridge, but it does **not** provide private routing or cryptographic identity verification. See [docs/ALIASES.md](docs/ALIASES.md) for the format and examples.

## Live bridge

Remove `--dry-run` only after the preflight run looks correct:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --meshtastic-channel 0 \
  --meshcore-channel 0 \
  --alias-file bridge_aliases.json
```

Stop it with `Ctrl+C`.

## Command-line options

| Option | Default | Purpose |
| --- | --- | --- |
| `--meshtastic-port` | required | Meshtastic USB serial path |
| `--meshcore-port` | required | MeshCore USB serial path |
| `--meshtastic-channel` | `0` | Meshtastic public channel index |
| `--meshcore-channel` | `0` | MeshCore public channel index |
| `--dedupe-seconds` | `120` | Time window used to suppress loop echoes |
| `--max-text-chars` | `180` | Maximum forwarded text length, including alias prefix |
| `--alias-file` | off | Optional local JSON map of source IDs to friendly aliases |
| `--dry-run` | off | Log actions without transmitting |
| `--debug` | off | Enable detailed logging |

## Tests

Python tests do not require radios. They test text filtering, broadcast detection, deduplication, alias formatting, and the public-only packet filter.

```bash
python -m unittest discover -s tests -v
```

For the Go helper:

```bash
cd tools/meshverse-doctor
go test ./...
go vet ./...
```

GitHub Actions runs these checks automatically for pushes and pull requests.

## Optional systemd service

A service template is included at `deploy/meshverse.service`. It reads serial paths and channel numbers from `/etc/mesh-verse/bridge.env`.

```bash
sudo useradd --system --home /opt/mesh-verse --shell /usr/sbin/nologin --groups dialout meshverse
sudo install -d -o meshverse -g dialout /opt/mesh-verse /etc/mesh-verse
sudo cp deploy/meshverse.env.example /etc/mesh-verse/bridge.env
sudo cp deploy/meshverse.service /etc/systemd/system/meshverse.service
sudoedit /etc/mesh-verse/bridge.env
sudo systemctl daemon-reload
sudo systemctl enable --now meshverse
sudo systemctl status meshverse
```

The service template expects a checked-out repository and virtual environment at `/opt/mesh-verse`. Adjust the paths if your installation lives elsewhere.

## Safety and privacy

- Keep this bridge on public channels only.
- Do not use it to relay private conversations without explicit consent from everyone involved.
- A bridge alias is a readable pseudonym, not a verified legal identity.
- Back up your configurations before changing radio firmware or settings.
- Start with `--dry-run` every time the hardware, port paths, channel layout, or alias map changes.

## Project direction

The goal is a small, understandable, auditable bridge: not a giant mystery box that decides which network traffic belongs somewhere else. Contributions that preserve the public-only MVP and add tests are welcome.
