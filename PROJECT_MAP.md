# Project map

This is the short version of how the repository fits together.

## The important files

| File | What it does |
| --- | --- |
| `translator.py` | The bridge. It reads public text from one radio and sends a copy through the other radio. |
| `identity_aliases.py` | Creates labels such as `MT-ALFA` and adds the visible `[MV/...]` marker. |
| `bridge_aliases.example.json` | Example file for choosing nicer local aliases. |
| `tests/` | Fake-radio tests. They test program logic without needing real hardware. |
| `tools/meshverse-doctor/` | Checks serial paths before the bridge is started. |
| `deploy/` | Optional systemd files for running the bridge on a Raspberry Pi. |

## What happens when a Meshtastic message arrives

1. `translator.py` receives a text packet from the Meshtastic USB radio.
2. It checks that the message is public and on the chosen channel.
3. It ignores DMs, telemetry, other channels, echoes, and messages that were already relayed.
4. It adds a label such as `[MV/MT-ALFA]`.
5. It asks the MeshCore USB radio to send the copied text on the chosen MeshCore channel.

The MeshCore-to-Meshtastic direction is the same process in reverse.

## Rules worth remembering

- The bridge needs **two radios**, not one.
- It connects **one public channel on each side**.
- It copies messages. It does not move or delete the original message.
- The `[MV/...]` marker is important. It stops another bridge from passing the same message around forever.
- Friendly aliases are only labels. They are not verified identities and do not create DMs.

## Where to start when changing something

- Changing message rules: `translator.py`
- Changing aliases: `identity_aliases.py`
- Adding a test: `tests/test_translator.py`
- Changing startup on Raspberry Pi: `deploy/meshverse.service`

Read `TODO.md` before adding a big feature. It lists the real hardware work that still matters more than shiny extras.
