# Mesh Verse

> **v0.1.0, experimental.** A small host-side bridge that copies public text between one Meshtastic channel and one MeshCore channel.

Mesh Verse runs on a Raspberry Pi, Mac, or Linux computer with **two separate radio devices connected by USB**:

```text
Meshtastic users
      ↓ LoRa
Meshtastic gateway radio ─USB─┐
                              ├─ host computer running Mesh Verse
MeshCore gateway radio ─USB───┘
      ↓ LoRa
MeshCore users
```

It does not turn one radio into both systems. One supported Meshtastic radio and one supported MeshCore Companion radio are required.

## What v0.1.0 does

- copies public text messages in both directions;
- bridges exactly one configured public channel on each side;
- labels forwarded messages with a visible envelope such as `[MV/MT-ALFA] hello`;
- generates stable pseudonymous aliases automatically, with optional local friendly aliases;
- rejects direct/private messages, telemetry, positions, files, binary packets, and raw LoRa frames;
- blocks local echoes and ignores messages that already carry a Mesh Verse relay envelope;
- provides `--check-config`, `--dry-run`, `--version`, hardware-free tests, and a read-only serial preflight helper.

## What it does not do

- private/direct-message routing between Meshtastic and MeshCore;
- identity verification or account linking;
- translation of human languages;
- automatic reconnection after a radio is unplugged;
- configuration or flashing of either radio;
- a global internet relay.

Messages are copied as ordinary public text. A relayed message remains visible on its original network and appears as a new public message on the other network.

## Safety model

Only public broadcast text from the configured channels is eligible for relay. The bridge never guesses that a private packet is public. Aliases are labels controlled locally by the bridge owner, not proof of a person's identity.

Use a controlled channel first. Do not bridge a community/default channel without the channel owner's permission. Follow the radio rules for your country or region.

## Requirements

- Python **3.10+**;
- one Meshtastic radio reachable over USB serial;
- one MeshCore **Companion** radio reachable over USB serial;
- a public channel set up on both systems;
- Go **1.20+** only for `meshverse-doctor`.

## Install

```bash
git clone https://github.com/logi-steel/mesh-verse.git
cd mesh-verse
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Check the installed release:

```bash
python translator.py --version
```

## Choose the two channels

Create one public channel on Meshtastic and one public channel on MeshCore. They can have the same human-friendly name, but they are separate channels in separate systems.

```text
Meshtastic: MV-Bridge-MT
MeshCore:   MV-Bridge-MC
```

Set the bridge to their channel indices. A message on any other channel is ignored.

## Find stable USB paths

Prefer stable Linux paths from `/dev/serial/by-id/` because `/dev/ttyACM0` and `/dev/ttyUSB0` may change after a reboot.

```bash
go run ./tools/meshverse-doctor \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio
```

## Validate before using radios

`--check-config` validates the arguments and alias file without opening a serial port or transmitting:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --meshtastic-channel 1 \
  --meshcore-channel 1 \
  --check-config
```

## First run: dry-run

Dry-run opens the radios and logs what it *would* forward, but never transmits a relay message.

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --meshtastic-channel 1 \
  --meshcore-channel 1 \
  --dry-run \
  --debug
```

Send a short public message from a controlled source on each side. Confirm that the logs show only the expected selected channel and that no private messages are considered.

## Live bridge

Remove `--dry-run` only after the dry-run looks correct:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --meshtastic-channel 1 \
  --meshcore-channel 1
```

Example result:

```text
Meshtastic source: "hello"
MeshCore sees:     [MV/MT-8F12AB] hello
```

The `[MV/...]` part is intentional. It labels the source side and stops another bridge from relaying an already relayed message a second time.

## Friendly aliases

Without a file, aliases are deterministic identifiers such as `MT-8F12AB` and `MC-90CDEF`. To assign friendly local labels, copy the example:

```bash
cp bridge_aliases.example.json bridge_aliases.json
```

Run with:

```bash
python translator.py ... --alias-file bridge_aliases.json --dry-run --debug
```

See [docs/ALIASES.md](docs/ALIASES.md) for the exact format. Keep `bridge_aliases.json` local. It is intentionally ignored by Git.

## systemd service

A service template lives in `deploy/meshverse.service`. It expects the repository and virtual environment at `/opt/mesh-verse` and the configuration at `/etc/mesh-verse/bridge.env`.

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

## Tests

The automated test suite uses fake radios. It verifies both relay directions, the relay envelope, echo suppression, private-message filtering, alias handling, and configuration validation. It cannot prove RF range or compatibility with every real firmware build.

```bash
python -m unittest discover -s tests -v
cd tools/meshverse-doctor
go vet ./...
go test ./...
```

## Release notes

See [CHANGELOG.md](CHANGELOG.md) and [v0.1.0 release notes](docs/releases/v0.1.0.md).

## License

Mesh Verse is released under the GNU GPL v3. See [LICENSE](LICENSE).
