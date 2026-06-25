# Mesh Verse
# WARNING THIS PROJECT IS IN 90% MADE BY AI
IT IS ONLY A EXPERIMENT TO PUBLIC
I AM STILL LEARNING CERTAIN LANGUAGES 
IN LATER RELEASES IT WILL BE MADE BY ME

# Back to main 

> **v0.1.0, experimental.** A small bridge that copies public text between one Meshtastic channel and one MeshCore channel.

```text
Meshtastic users
      ↓ LoRa
Meshtastic radio ─USB─┐
                      ├─ Raspberry Pi / Mac / Linux host
MeshCore radio ─USB───┘
      ↓ LoRa
MeshCore users
```

You need **two separate USB radios**: one running Meshtastic and one running MeshCore Companion. One radio cannot run both systems at once.

## What it does

- Copies public text in both directions.
- Bridges one chosen channel on each network.
- Adds a source label, for example `[MV/MT-ALFA] hello`.
- Ignores private messages, telemetry, positions, files, and raw packets (private messages will be in the next versions).
- Blocks obvious echoes and messages already marked as relayed.

It sends a copy of a message. The original stays on its first network.

## Quick start

```bash
git clone https://github.com/logi-steel/mesh-verse.git
cd mesh-verse
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Check the program version:

```bash
python translator.py --version
```

Use a separate public channel for the bridge on each side, for example:

```text
Meshtastic: MV-Bridge-MT
MeshCore:   MV-Bridge-MC
```

Find the two USB paths. On Linux, prefer `/dev/serial/by-id/...` because `/dev/ttyACM0` and `/dev/ttyUSB0` can change after a reboot.

```bash
go run ./tools/meshverse-doctor \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio
```

Validate the setup without opening radios:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --meshtastic-channel 1 \
  --meshcore-channel 1 \
  --check-config
```

Then run a safe test. It listens normally but does not transmit relayed messages:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --meshtastic-channel 1 \
  --meshcore-channel 1 \
  --dry-run \
  --debug
```

When the log looks right, remove `--dry-run`.

## Friendly aliases

The bridge makes stable labels automatically. To choose your own local names:

```bash
cp bridge_aliases.example.json bridge_aliases.json
python translator.py ... --alias-file bridge_aliases.json --dry-run --debug
```

Read [docs/ALIASES.md](docs/ALIASES.md) for the format. Aliases are labels only. They do not prove identity or create private-message routes.

## Main docs

- [PROJECT_MAP.md](PROJECT_MAP.md): what each part of the project does
- [TODO.md](TODO.md): the real hardware work still left
- [docs/SETUP.md](docs/SETUP.md): longer setup guide
- [CHANGELOG.md](CHANGELOG.md): release history

## Not supported (for now)

- Direct/private messages
- Human-language translation
- Automatic reconnect after unplugging a radio
- Files, telemetry, GPS, or raw LoRa packets
- A global internet relay

## Tests

```bash
python -m unittest discover -s tests -v
cd tools/meshverse-doctor
go vet ./...
go test ./...
```

The tests use fake radios. They check program logic, not real radio range or every firmware version.

## Running on a Raspberry Pi

`deploy/meshverse.service` is an optional systemd template for running Mesh Verse on boot. It reads settings from `/etc/mesh-verse/bridge.env`.

## License

GNU GPL v3. See [LICENSE](LICENSE).

## SELF-HOSTING (how to do it and is it worth it) (it is not)
# What is it 
self hosting a mesh-verse is not that big of a problem
you need 
**A Raspberry pi (the recomended version for medium usage is pi4 4gb ) and up to newest verison**

**2 nodes wich one will be operating in meshcore and the second on meshtastic**

**A usb cable to connect the nodes to raspberry pi**

**antenas to both radios (you can buy all in one radio with antena like the T-Echo from LILY-GO) for the connection to work**

**stable power (or working with power bank but this is a lottery wich compuetrs like raspberry pi dont like)**

**FOR CLARITY you can use whatever computer you like. but it must have enought powwer. but you can run it on literaly potato pc (if 2gb ram and 2 cores are potato pc then yes)**


# Firmware 
for the potato you need
my (not realy mine) program 
on 1 node instal meshtastic (https://github.com/Xinyuan-LilyGO/T-Echo/blob/main/firmware/README.MD)
on second instal meshcore (https://nodakmesh.org/meshcore/setup) 
and on potato 
linux| macos| windows (MacOS isn't testes yet so take it as "its unix it works the same")
#REMEMBER TO BACKUP ANYTHING ON YOUR DEVICES BEFORE DOING THIS !!!


# CANAL 
Make one chanell on the meshtastic side 
And one on the meshcore side
name them similary so you can see your own chanell 
The only tech limitation currently is that you can't send dm's 


