# Mesh Verse aliases

Mesh Verse relays public-channel text only. Every copied message has a visible relay envelope:

```text
[MV/MT-ALFA] hello from Meshtastic
[MV/MC-BRAVO] hello from MeshCore
```

`MV` means Mesh Verse. `MT-...` means the source was Meshtastic, while `MC-...` means the source was MeshCore.

## Why the envelope is visible

The envelope helps people recognise the source side and prevents a second bridge from copying an already relayed message again. Do not remove it. A message beginning with `[MV/... ]` is deliberately ignored by Mesh Verse when received as input.

## What aliases are not

An alias is a local readability and privacy label. It is not:

- a private-message address;
- a shared account between systems;
- a verified identity;
- proof of who typed the message.

Replies remain ordinary public messages on the selected channel.

## Automatic aliases

No setup is required. A source ID gets a stable fallback alias after a restart:

```text
Meshtastic source !a1b2c3d4 -> MT-8F12AB
MeshCore source a1b2c3d4     -> MC-90CDEF
```

The original source identifier is not placed in the relayed message.

## Friendly aliases

1. Copy the example config:

```bash
cp bridge_aliases.example.json bridge_aliases.json
```

2. Run a controlled dry-run with `--debug` and send one public test message from each source radio.

3. Put the source identifiers shown in the local log into `bridge_aliases.json`:

```json
{
  "version": 1,
  "aliases": {
    "meshtastic": {
      "!a1b2c3d4": "MT-ALFA"
    },
    "meshcore": {
      "a1b2c3d4": "MC-BRAVO"
    }
  }
}
```

4. Start Mesh Verse with the file:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --alias-file bridge_aliases.json \
  --dry-run \
  --debug
```

Aliases may use only ASCII letters, digits, `-`, or `_`, and must be 1-24 characters long.

## Keep the map local

`bridge_aliases.json` is ignored by Git because it links local source identifiers to labels you chose. The example file contains fake values only.
