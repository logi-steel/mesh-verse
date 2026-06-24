# TODO

This is a small project. Keep the next steps practical.

## Before calling the bridge hardware-tested

- [ ] Test Meshtastic → MeshCore with two real USB radios.
- [ ] Test MeshCore → Meshtastic with two real USB radios.
- [ ] Confirm that the real MeshCore Companion event fields match what the Python library exposes.
- [ ] Test a restart while both radios stay connected.
- [ ] Test what happens when one USB radio is unplugged and plugged back in.
- [ ] Test a long message and confirm that the relay label still fits.
- [ ] Check the service starts after a Raspberry Pi reboot.
- [ ] Write down the exact working firmware versions and radio models.

## Good next features

- [ ] Clearer error message when a USB path disappears.
- [ ] Optional automatic reconnect after a radio is unplugged.
- [ ] A small status page or terminal command showing whether both radios are connected.
- [ ] A simple way to export bridge logs for debugging.

## Do not rush these

- Direct messages: needs a real identity and contact-mapping design first.
- Files, telemetry, GPS, or raw packets: keep them out until there is a clear reason and a safe design.
- Multiple bridges on the same pair of channels: test this carefully before advertising it as supported.
