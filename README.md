# Mesh Verse

> **Status: experimental MVP.** Mesh Verse is currently an AI-assisted prototype maintained by the repository owner. It is not hardware-tested or production-ready yet, so use it first with `--dry-run` and only on radios you control.

Mesh Verse is a deliberately narrow bridge between a **Meshtastic public text channel** and a **MeshCore public text channel**.

## What it does

- forwards public text-channel messages in both directions;
- keeps a short duplicate cache to reduce simple bridge loops;
- lets you choose a channel index on each side;
- has a dry-run mode that logs decisions without transmitting;
- includes `meshverse-doctor`, a read-only serial-port preflight helper.

## What it does not do

- direct/private messages;
- position data, telemetry, files, binary packets, or raw LoRa frames;
- automatic contact matching between networks;
- radio configuration, firmware flashing, or frequency changes.

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

## Live bridge

Remove `--dry-run` only after the preflight run looks correct:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --meshtastic-channel 0 \
  --meshcore-channel 0
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
| `--max-text-chars` | `180` | Maximum forwarded message length |
| `--dry-run` | off | Log actions without transmitting |
| `--debug` | off | Enable detailed logging |

## Tests

Python tests do not require radios. They test text filtering, broadcast detection, deduplication, and the public-only packet filter.

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
- Back up your configurations before changing radio firmware or settings.
- Start with `--dry-run` every time the hardware, port paths, or channel layout changes.

## Project direction

The goal is a small, understandable, auditable bridge: not a giant mystery box that decides which network traffic belongs somewhere else. Contributions that preserve the public-only MVP and add tests are welcome.
