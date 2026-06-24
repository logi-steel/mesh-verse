# Pseudonymous Relay Aliases

Mesh Verse relays **public-channel text only**. When it forwards a message, it prefixes the text with a source label:

```text
[MT-ALFA] hello from Meshtastic
[MC-BRAVO] hello from MeshCore
```

This lets people on the other network tell messages apart without relaying the sender's original display name.

## What an alias is, and is not

An alias is a **local display label controlled by the bridge owner**.

It is useful for privacy and readability. It is **not**:

- a private-message address;
- a shared MeshCore/Meshtastic account;
- cryptographic identity verification;
- proof that a human rather than another node typed a message.

Mesh Verse still broadcasts each forwarded message to the selected public channel. It does not use aliases to route a reply to a specific person.

## Automatic aliases

You do not need to configure anything for basic aliases. When no alias map is supplied, the bridge derives a stable label from the source identifier:

```text
Meshtastic source !a1b2c3d4 -> MT-8F12AB
MeshCore source a1b2c3d4     -> MC-90CDEF
```

The prefix identifies the originating network:

- `MT-...` means the text came from Meshtastic;
- `MC-...` means the text came from MeshCore.

The fallback is deterministic: the same source receives the same fallback alias after a restart. The original identifier itself is not placed inside the relayed message.

## Friendly custom aliases

1. Copy the example file:

```bash
cp bridge_aliases.example.json bridge_aliases.json
```

2. Run a controlled dry-run with debug logging:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --dry-run \
  --debug
```

3. Send one ordinary **public channel** test message from each source device.

4. Read the local terminal log. Mesh Verse prints lines such as:

```text
Meshtastic source ID !a1b2c3d4 resolved to alias MT-8F12AB
MeshCore source ID a1b2c3d4 resolved to alias MC-90CDEF
```

5. Put those source IDs into `bridge_aliases.json`, then choose an alias. The alias must contain only ASCII letters, numbers, `-`, or `_`, and must be 1–24 characters long.

Example:

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

6. Restart the bridge with the file:

```bash
python translator.py \
  --meshtastic-port /dev/serial/by-id/your-meshtastic-radio \
  --meshcore-port /dev/serial/by-id/your-meshcore-radio \
  --alias-file bridge_aliases.json \
  --dry-run \
  --debug
```

Now source `!a1b2c3d4` appears on MeshCore as `[MT-ALFA] ...`, and source `a1b2c3d4` appears on Meshtastic as `[MC-BRAVO] ...`.

## Keep the map local

`bridge_aliases.json` is ignored by Git. Keep it local because it links source identifiers to your chosen labels. The public `bridge_aliases.example.json` contains only fake values.

## Replying across the bridge

For this MVP, a person replies by writing another message on the public channel. For example:

```text
[MT-ALFA] Can someone test this?
[MC-BRAVO] Received.
```

The bridge does **not** automatically turn a reply to `MT-ALFA` into a Meshtastic direct message. A future private-routing design would need an explicit owner-approved mapping of full device/contact identities and separate consent rules. A nickname alone is not enough, because nicknames can collide or be changed.

## Message length

The alias prefix counts toward `--max-text-chars`. With the default limit of 180 characters, this is rarely a problem. If a message is too long, Mesh Verse keeps the alias and visibly truncates the text with `…`.
