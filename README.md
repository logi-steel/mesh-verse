# Mesh Verse

> **v0.1.0, experimental.** A small host-side bridge that copies public text between one Meshtastic channel and one MeshCore Companion channel.

## AI disclosure

Mesh Verse is a public learning project. Most of the current v0.1 code and documentation were created with AI assistance.

I am using this project to learn how the software, LoRa nodes, serial connections, testing, and self-hosting work. I plan to understand, review, and write more of future updates myself.

## What Mesh Verse is

Mesh Verse is not a new firmware, cloud service, or replacement for Meshtastic or MeshCore.

It is a small translator running on a host computer. The host connects to two separate LoRa nodes over USB:

```text
Meshtastic users
      ↓ LoRa
Meshtastic node ─USB─┐
                     ├─ Raspberry Pi / Linux PC / Mac
MeshCore node ─USB───┘
      ↓ LoRa
MeshCore users
```

The host receives public text from one node over USB serial and asks the other node to transmit a labelled copy on its own network. The LoRa nodes and their antennas still handle all wireless communication.

## What it does

- Copies public text messages in both directions.
- Bridges one selected public channel on each network.
- Adds a visible source label such as `[MV/MT-ALFA] hello`.
- Uses a duplicate cache and relay marker to reduce message loops.
- Supports `--check-config`, `--dry-run`, `--debug`, and `meshverse-doctor`.

## What it does not do

- Direct or private messages.
- Sender identity verification or contact linking.
- Human-language translation.
- Files, telemetry, GPS positions, binary data, or raw LoRa packets.
- Automatic recovery after a USB node is unplugged.
- A global internet relay.

A relayed message is a new public message on the destination network. The original message stays on its source network.

# Self-hosting a Mesh Verse relay

## 1. Hardware you need

### A host computer

Use a Raspberry Pi, Linux computer, or Mac as the host.

- Raspberry Pi 4 with 4 GB RAM is more than enough for a permanent relay.
- A Linux mini PC also works well.
- A Mac is useful for a manual first test.
- The included always-on service template is for Linux and Raspberry Pi.

### Two separate LoRa nodes

You need:

1. One node running Meshtastic.
2. One node running MeshCore Companion.

A node can be a device such as a T-Echo, T-Deck, T-Beam, Heltec-based node, or another compatible LoRa device. Check support for the exact model and firmware before buying or flashing it.

One physical node can run only one firmware at a time. A T-Echo flashed with Meshtastic can be the Meshtastic side of the relay, but it cannot also be the MeshCore side. Mesh Verse needs two nodes.

### Other hardware

- Two USB **data** cables. Charging-only cables will not work.
- Two USB ports or a powered USB hub.
- Antennas for both nodes.
- Stable power for the host and nodes.

Internet is useful for installation and updates. The local relay does not need internet after setup.

## 2. Prepare both networks first

Mesh Verse does not flash firmware, configure radio regions, or create channels for you. Make sure both networks work by themselves before starting the bridge.

### Meshtastic side

1. Flash supported Meshtastic firmware onto the gateway node.
2. Set the correct regional radio settings.
3. Create a small controlled test channel.
4. Confirm that the gateway node can exchange a normal broadcast message with another Meshtastic node.

### MeshCore side

1. Flash supported MeshCore Companion firmware onto the gateway node.
2. Configure lawful radio settings for your region.
3. Create a small controlled test channel.
4. Confirm that the gateway node can exchange a normal channel message with another MeshCore node.

For a proper end-to-end test, you normally need four LoRa nodes: two gateway nodes connected to the host, plus one test node on each network.

## 3. Create dedicated bridge channels

Create one public broadcast channel on each network. Keep them separate from busy community or default channels while testing.

```text
Meshtastic: MV-Bridge-MT
MeshCore:   MV-Bridge-MC
```

The names can be similar, but the channels are still independent. Mesh Verse needs the channel index from each side.

Public means a broadcast message to everyone on the configured channel. Direct messages are deliberately ignored. Tell people using the bridged channels that their public messages may appear on the other network.

## 4. Connect both nodes over USB

```text
Meshtastic node ── USB ──┐
                          ├── host computer running Mesh Verse
MeshCore node ──── USB ──┘
```

USB provides power and a serial-data connection. The host reads messages from each node through USB serial, while the nodes keep talking to nearby users through LoRa and their antennas.

On Linux, find stable serial paths with:

```bash
ls -l /dev/serial/by-id/
```

Use paths from `/dev/serial/by-id/` instead of `/dev/ttyUSB0` or `/dev/ttyACM0`. The short paths can change after a reboot.

On macOS, list likely serial paths with:

```bash
ls /dev/cu.*
```

## 5. Install Mesh Verse

```bash
git clone https://github.com/logi-steel/mesh-verse.git
cd mesh-verse
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install Go too if you want to use `meshverse-doctor`.

Check the installed version:

```bash
python translator.py --version
```

## 6. Verify the USB setup

Run the read-only preflight helper with your serial paths:

```bash
go run ./tools/meshverse-doctor \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-node \
  --meshcore-port /dev/serial/by-id/your-meshcore-node
```

Then validate the configuration before opening the serial ports:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-node \
  --meshcore-port /dev/serial/by-id/your-meshcore-node \
  --meshtastic-channel 0 \
  --meshcore-channel 0 \
  --check-config
```

Fix every configuration error before continuing.

## 7. Test safely with dry-run

Start with `--dry-run`. Mesh Verse listens normally and logs what it would forward, but it does not transmit relayed messages.

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-node \
  --meshcore-port /dev/serial/by-id/your-meshcore-node \
  --meshtastic-channel 0 \
  --meshcore-channel 0 \
  --dry-run \
  --debug
```

Test both directions:

1. Send a short public message from a Meshtastic test node.
2. Confirm that the terminal logs a Meshtastic → MeshCore relay attempt.
3. Send a short public message from a MeshCore test node.
4. Confirm that the terminal logs a MeshCore → Meshtastic relay attempt.
5. Confirm that direct messages, telemetry, position packets, other channels, and messages already marked `[MV/...]` are ignored.

## 8. Start the live relay

When dry-run works in both directions, remove `--dry-run`:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-node \
  --meshcore-port /dev/serial/by-id/your-meshcore-node \
  --meshtastic-channel 0 \
  --meshcore-channel 0 \
  --debug
```

The host must stay powered on for the relay to exist. The `[MV/...]` marker is intentional. It shows the source side and helps prevent message loops.

## 9. Run continuously on Raspberry Pi or Linux

For a permanent relay, use the included `deploy/meshverse.service` systemd template. It expects the project in `/opt/mesh-verse` and settings in `/etc/mesh-verse/bridge.env`.

Use stable `/dev/serial/by-id/...` paths in `bridge.env`. After installing and enabling the service, check it with:

```bash
sudo systemctl status meshverse
sudo journalctl -u meshverse -f
```

If a USB node is unplugged, reconnect it and restart the service. Automatic node reconnection is not currently supported.

## 10. Friendly aliases

Mesh Verse creates stable labels automatically. To choose local friendly names:

```bash
cp bridge_aliases.example.json bridge_aliases.json
python translator.py ... --alias-file bridge_aliases.json --dry-run --debug
```

Read [docs/ALIASES.md](docs/ALIASES.md) for the format. Aliases are local labels only, not verified identities.

## 11. Privacy, safety, and limits

- Relay only public text from the selected bridge channels.
- Do not use aliases containing personal information.
- Do not publish logs containing private data or device identifiers.
- Use legal regional LoRa settings.
- Run only one Mesh Verse instance for the same pair of channels during testing.
- The test suite uses fake nodes. It tests program logic, not RF range or every firmware version.

## 12. Troubleshooting

### A node is not detected

- Check that the USB cable supports data.
- Check that the node is powered on.
- Check the serial path.
- On Linux, check USB permissions and the `dialout` group.
- Try a powered USB hub if a node disconnects under load.

### The relay starts but messages do not cross

- Check both channel indexes.
- Check that the message is a public broadcast.
- Check that the node has a working LoRa link to a test node.
- Check that `--dry-run` is disabled.
- Check whether the message already includes an `[MV/...]` marker.

### It worked once and then stopped

- Check terminal output or `journalctl` logs.
- Check whether either USB node disconnected.
- Check whether the serial path changed after a reboot.
- Restart the service after reconnecting the missing node.

## Documentation

- [PROJECT_MAP.md](PROJECT_MAP.md): what each important file does.
- [docs/SETUP.md](docs/SETUP.md): longer first-time setup guide.
- [docs/ALIASES.md](docs/ALIASES.md): local alias file format.
- [TODO.md](TODO.md): real hardware work still left.
- [CHANGELOG.md](CHANGELOG.md): release history.

## Tests

```bash
python -m unittest discover -s tests -v
cd tools/meshverse-doctor
go vet ./...
go test ./...
```

## License

Mesh Verse is released under the GNU GPL v3. See [LICENSE](LICENSE).
