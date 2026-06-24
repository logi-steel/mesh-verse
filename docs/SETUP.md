# First Real Setup

This guide explains the physical setup, the software setup, and what Mesh Verse actually does.

## 1. What Mesh Verse is

Mesh Verse is a **gateway** between two different LoRa mesh networks:

```text
Meshtastic users
      |
      |  Meshtastic radio settings + shared channel
      v
[ Meshtastic gateway radio ] -- USB -- [ MacBook or Raspberry Pi ] -- USB -- [ MeshCore gateway radio ]
                                                                                 |
                                                                                 |  MeshCore radio settings + shared channel
                                                                                 v
                                                                           MeshCore users
```

The computer runs `translator.py`. It listens to public channel text received by one gateway radio and transmits the same text through the other gateway radio.

This is not firmware for a radio and it is not a new mesh protocol. It is a small translator sitting between two already-working networks.

## 2. What you need

### Required hardware

1. **One host computer**
   - Use a MacBook for the first test.
   - Use a Raspberry Pi, Linux mini PC, or another always-on computer later if you want the bridge online continuously.

2. **One Meshtastic radio** connected by a USB **data** cable.
   - It must already run Meshtastic firmware and be visible as a serial device.

3. **One MeshCore Companion radio** connected by a second USB **data** cable.
   - It must already run compatible MeshCore Companion firmware and be visible as a serial device.

4. A powered USB hub if the host has too few ports or either radio is unstable from USB power alone.

### Important: one radio is not enough

The bridge opens two radio connections at the same time. One physical device flashed with one firmware provides only one connection.

A T-Deck or similar device can be the **Meshtastic side** *or* the **MeshCore side** at a time, but it cannot be both sides of this bridge simultaneously. You need two separate radios for the bridge itself.

### Minimum test network

The bridge needs two gateway radios. To prove messages work in both directions, also have:

- one extra Meshtastic node that can send or receive a test message;
- one extra MeshCore node that can send or receive a test message.

So a proper end-to-end test normally uses four radios total: two gateway radios plus one client node on each network.

## 3. Configure the radios before starting Mesh Verse

Mesh Verse does not configure frequencies, regions, channel keys, or firmware. Configure each network with its official client first.

### Meshtastic side

1. Flash supported Meshtastic firmware on the Meshtastic gateway radio.
2. Set the correct LoRa region for where you operate.
3. Give the gateway a clear name, for example `meshverse-mt-gateway`.
4. Put the gateway and your Meshtastic test node on the same channel index, with matching channel settings.
5. Send a normal broadcast message between Meshtastic nodes before involving Mesh Verse.

### MeshCore side

1. Flash supported MeshCore **Companion** firmware on the MeshCore gateway radio.
2. Set the correct radio parameters for your local lawful configuration.
3. Give the gateway a clear name, for example `meshverse-mc-gateway`.
4. Configure a MeshCore channel and make sure the MeshCore gateway and test node use the same channel index and shared channel secret.
5. Send a normal channel message between MeshCore nodes before involving Mesh Verse.

### What “public channel” means here

“Public” means a broadcast message to everyone on that configured channel. It does **not** mean the RF traffic must be unencrypted. A shared channel secret is fine. Direct messages are deliberately ignored by Mesh Verse.

Do not bridge a default/global channel until you have tested with a small controlled channel. A bridge that sprays accidental test traffic into a crowded mesh is how a weekend hobby becomes a tiny municipal incident.

## 4. Install Mesh Verse on a MacBook

This is the easiest first setup.

1. Install the tools:

```bash
brew install python go
```

2. Clone and install Mesh Verse:

```bash
git clone https://github.com/logi-steel/mesh-verse.git
cd mesh-verse
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Connect both gateway radios by USB, then list likely serial ports:

```bash
ls /dev/cu.*
```

Typical paths look like `/dev/cu.usbserial-...` or `/dev/cu.SLAB_USBtoUART`.

4. Run the safe port checker. Replace the two example paths with your own:

```bash
go run ./tools/meshverse-doctor \
  --meshtastic-port /dev/cu.usbserial-MESHTASTIC \
  --meshcore-port /dev/cu.usbserial-MESHCORE
```

`meshverse-doctor` is read-only: it does not open, transmit through, configure, or reset a radio.

## 5. First run: dry-run only

Start the bridge in dry-run mode before allowing any radio transmission:

```bash
python translator.py \
  --meshtastic-port /dev/cu.usbserial-MESHTASTIC \
  --meshcore-port /dev/cu.usbserial-MESHCORE \
  --meshtastic-channel 0 \
  --meshcore-channel 0 \
  --dry-run \
  --debug
```

Replace the port paths and channel numbers with your own values.

Expected behaviour:

1. A Meshtastic test node sends a broadcast to Meshtastic channel `0`.
2. The terminal logs `Meshtastic -> MeshCore ...`.
3. The terminal logs `[dry-run] Would send to MeshCore channel 0`.
4. Nothing is actually transmitted because `--dry-run` is enabled.

Repeat in the other direction with a MeshCore channel message. You should see `MeshCore -> Meshtastic ...` and a dry-run log.

If you see direct messages, telemetry, location packets, or another channel in the log, stop. That is not the expected test result.

## 6. Live test

Only when both dry-run directions look correct, start the live bridge by removing `--dry-run`:

```bash
python translator.py \
  --meshtastic-port /dev/cu.usbserial-MESHTASTIC \
  --meshcore-port /dev/cu.usbserial-MESHCORE \
  --meshtastic-channel 0 \
  --meshcore-channel 0
```

Now test carefully:

1. Send `MT test 1` from the extra Meshtastic node.
2. Confirm it appears on the MeshCore test node.
3. Send `MC test 1` from the extra MeshCore node.
4. Confirm it appears on the Meshtastic test node.
5. Stop with `Ctrl+C` once the test is complete.

## 7. Run it continuously later

For a permanent bridge, move the repository to a Raspberry Pi or Linux mini PC and use the included `deploy/meshverse.service` systemd template.

On Linux, use stable USB aliases when available:

```bash
ls -l /dev/serial/by-id/
```

Prefer paths from `/dev/serial/by-id/` over `/dev/ttyUSB0` or `/dev/ttyACM0`. The short names can swap after a reboot when two radios are connected.

See the `Optional systemd service` section in the main README for the service installation commands.

## 8. Current MVP limitations

Know these before treating the bridge like a production service:

- Relayed messages are sent by the gateway radio, so receivers do not get the original sender identity.
- Only public channel text is relayed. Direct messages, position data, telemetry, files, binary data, and raw LoRa frames are ignored.
- The loop-prevention cache compares message text for 120 seconds. Two independent users sending the exact same short text in opposite directions during that window can cause one message to be ignored.
- The bridge has no database, history, web dashboard, or moderation tools.
- If a USB device is disconnected or the host restarts, manually restart the bridge for now.
- Run only one Mesh Verse bridge for a given pair of channels during testing. Multiple bridges can cause duplicate traffic or loops.

## 9. Safe first configuration checklist

- [ ] Meshtastic radio works with another Meshtastic node before the bridge starts.
- [ ] MeshCore Companion radio works with another MeshCore node before the bridge starts.
- [ ] Both gateway radios use USB data cables, not charge-only cables.
- [ ] The host can see two distinct serial paths.
- [ ] `meshverse-doctor` accepts both paths and reports different devices.
- [ ] Dry-run shows only the intended channel traffic.
- [ ] A live test works in both directions using a small controlled channel.
- [ ] Everyone using the bridged public channels knows that messages may cross to the other network.

## 10. Useful official references

- Meshtastic Python library and serial interface documentation: https://python.meshtastic.org/
- Meshtastic installation guidance: https://meshtastic.org/docs/software/python/cli/installation/
- MeshCore firmware and project documentation: https://github.com/meshcore-dev/MeshCore
- MeshCore Python library documentation: https://pypi.org/project/meshcore/
