# FCS Keys

Automatically downloads Apple's Full Chain Signature (FCS) encryption keys for IPSW firmware images. A GitHub Actions workflow runs hourly to discover new builds via [AppleDB](https://github.com/littlebyteorg/appledb) and fetch their keys using [blacktop/ipsw](https://github.com/blacktop/ipsw).

## What are FCS keys?

Apple signs firmware images (IPSWs) with Full Chain Signature keys. These keys are needed to decrypt the disk images inside an IPSW (e.g. the root filesystem DMG). This repository collects and archives those keys for iOS, iPadOS, and macOS builds.

## Repository structure

```
.
├── decrypt.py                # Decrypt DMGs from an IPSW using keys in this repo
├── update.py                 # Main update script
├── run_local.sh              # Run update.py locally via Docker
├── fcs-keys.json             # All FCS keys in a single JSON file (hash -> base64 PEM)
├── keys/                     # Individual PEM key files organized by OS and build
│   ├── iOS/<buildid>/        # e.g. keys/iOS/22A3354/*.pem
│   ├── iPadOS/<buildid>/
│   └── macOS/<buildid>/
├── iOS_fcs.json              # Per-OS tracking logs for FCS key downloads
├── iOS_key.json              # Per-OS tracking logs for PEM key downloads
├── iPadOS_fcs.json
├── iPadOS_key.json
├── macOS_fcs.json
├── macOS_key.json
└── .github/workflows/
    └── update_and_release.yml
```

## How it works

### Workflow ([update_and_release.yml](.github/workflows/update_and_release.yml))

The GitHub Actions workflow runs on a cron schedule (hourly at minute 42) inside the `blacktop/ipsw` container:

1. **Install dependencies** — Installs `curl`, `git`, `jq`, `python3` into the container.
2. **Run `update.py`** — Discovers new builds and downloads their keys (see below).
3. **Commit and push** — If any keys changed, commits to `main` and pushes.
4. **Update release** — Updates the `v1.0.0` release in-place with fresh `keys.tbz2` and `fcs-keys.json` artifacts. A self-healing check forces a release rebuild if the expected single release is missing.

The workflow can also be triggered manually via `workflow_dispatch`.

### Update script ([update.py](update.py))

`update.py` runs two updaters sequentially:

1. **`FCS_Updater`** — Downloads FCS keys in JSON format (`ipsw dl appledb --fcs-keys-json`). All keys are aggregated into `fcs-keys.json`, a flat mapping of key hash to base64-encoded PEM private key.

2. **`Key_Updater`** — Downloads FCS keys as individual PEM files (`ipsw dl appledb --fcs-keys`). Each PEM is stored under `keys/<OS>/<buildid>/` and renamed to its MD5 hash to deduplicate keys that `ipsw` reports with different filenames but identical contents.

Both updaters share the same retry logic via the `BuildIterator` base class:
- Builds are discovered by walking the AppleDB data (`~/.config/ipsw/appledb/osFiles/`).
- Each build is tracked in a per-OS JSON log (e.g. `iOS_fcs.json`).
- A build's tracking value is:
  - An `int` (0–9): number of download attempts so far (still retrying).
  - `true`: download succeeded permanently.
  - `false`: download failed permanently after 10 attempts.
- The log is saved after every individual download attempt so progress is never lost.

## Decrypting an IPSW

`decrypt.py` extracts and decrypts DMG disk images from an IPSW file. It reads the IPSW's `BuildManifest.plist` to identify the build and OS, locates the matching key(s) in this repository, and runs `ipsw extract --dmg --pem-db` to decrypt.

```bash
# Decrypt all DMG types from an IPSW (auto-detects build/OS)
./decrypt.py iPhone16,2_18.0_22A5307f_Restore.ipsw

# Extract only the system DMG to a specific directory
./decrypt.py --dmg sys -o /tmp/decrypted firmware.ipsw

# Use a downloaded fcs-keys.json from the release
./decrypt.py --pem-db ~/Downloads/fcs-keys.json firmware.ipsw
```

Requires the [`ipsw`](https://github.com/blacktop/ipsw) tool to be installed.

## Downloading keys

### From the release

The latest keys are always available from the [Current Release](../../releases/tag/v1.0.0):

- **`fcs-keys.json`** — All keys as a single JSON file.
- **`keys.tbz2`** — All individual PEM files as a compressed tarball.

### Running locally

Use `run_local.sh` to run the update process locally in Docker:

```bash
./run_local.sh
```

This uses the same `blacktop/ipsw` container image as CI. Downloaded keys will appear in the working directory.