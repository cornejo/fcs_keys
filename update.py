#! /usr/bin/env python3

import hashlib
import json
import os
import re
import requests
import shutil
import subprocess
import tempfile

from pathlib import Path


SUPPORTED_OSES = ["iOS", "iPadOS"]
MIN_BUILD_VER = 22
KEYS_DIR = "keys"


class FCS_Downloader:
    def __init__(self):
        self.KEY_LOG_FILE = "key_log.json"
        self.APPLEDB_DIR = Path("~/.config/ipsw/appledb").expanduser()

    def _load_keylog(self, apple_os: str) -> dict[str, int | bool]:
        # Format is
        # {buildid: bool if success/fail, otherwise int for number of attempts}

        key_log: dict[str, int | bool] = {}
        try:
            with open(f"{apple_os}_{self.KEY_LOG_FILE}") as f:
                key_log = json.load(f)
        except FileNotFoundError:
            pass
        return key_log

    def _save_keylog(self, apple_os: str, key_log: dict[str, int | bool]):
        with open(f"{apple_os}_{self.KEY_LOG_FILE}", "w") as f:
            json.dump(key_log, f, sort_keys=True, indent=2)

    def update_keys(self):
        # The original version of this function would attempt to get the keys for
        # the 'latest' OS version but this would fail at times for reasons unclear
        # This new technique gets the list of known build id's and attempts to download
        # each directly. It will attempt each build id 10 times before giving up
        # Because it's not easy (possible?) to get build id's or versions for devices using ipsw
        # we need to peek into appledb

        max_attempts = 10

        # Initial download and prepopulate the git repo
        subprocess.check_output(["ipsw", "dl", "appledb", "--os", "iOS", "--json"])

        appledb_found = False

        for apple_os in ["iOS", "iPadOS", "macOS"]:
            key_log = self._load_keylog(apple_os)

            for _root, _dirs, files in os.walk(self.APPLEDB_DIR / "osFiles" / apple_os):
                for f in files:
                    if f.endswith(".json"):
                        appledb_found = True
                        buildid = f.rsplit(".", 1)[0]

                        if buildid not in key_log:
                            key_log[buildid] = 0

            for buildid in key_log:
                val = key_log[buildid]
                if isinstance(val, bool):
                    # Already succeeded/failed
                    continue

                print(f"Trying {buildid} for {apple_os}, attempt {val + 1}/{max_attempts}")
                try:
                    subprocess.check_call(
                        [
                            "ipsw",
                            "dl",
                            "appledb",
                            "--os",
                            apple_os,
                            "--build",
                            buildid,
                            "--fcs-keys-json",
                            "--verbose",
                            "--confirm",
                        ]
                    )
                    key_log[buildid] = True
                except subprocess.CalledProcessError:
                    key_log[buildid] = val + 1
                    if key_log[buildid] >= max_attempts:
                        key_log[buildid] = False

                # Save immediately on mutate
                self._save_keylog(apple_os, key_log)

        if appledb_found is False:
            raise Exception(f"No appledb data found in {self.APPLEDB_DIR}")

        # Sort fcs-keys to make it easier for the git commit, but also for human eyes
        with open("fcs-keys.json", "r") as f:
            all_keys = json.load(f)
        with open("fcs-keys.json", "w") as f:
            json.dump(all_keys, f, sort_keys=True, indent=2)


def update_fcs_keys_json():
    for apple_os in ["iOS", "iPadOS", "macOS"]:
        print(f"Updating fcs.keys.json for {apple_os}")
        # This fails for new "latest" releases that don't use fcs keys
        # subprocess.check_call(["ipsw", "dl", "appledb", "--os", apple_os, "--fcs-keys-json", "--latest", "--confirm"])
        subprocess.call(["ipsw", "dl", "appledb", "--os", apple_os, "--fcs-keys-json", "--latest", "--confirm"])


def download_build_keys(apple_os: str, build: str):
    os_dir = f"{KEYS_DIR}/{apple_os}"
    os.makedirs(os_dir, exist_ok=True)

    key_dir = f"{os_dir}/{build}"

    if os.path.exists(key_dir):
        # Already downloaded/attempted, ignore
        return

    with tempfile.TemporaryDirectory() as tempdir:
        print(f"Build {build}")
        subprocess.check_call(
            [
                "ipsw",
                "dl",
                "appledb",
                "--os",
                apple_os,
                "--build",
                build,
                "--fcs-keys",
                "--output",
                tempdir,
                "--confirm",
            ]
        )

        for root, _dirs, files in os.walk(tempdir):
            for file in sorted(files):
                if file.endswith(".pem"):
                    os.makedirs(key_dir, exist_ok=True)
                    # The filename that 'ipsw' has used suggests it only applies to a specific
                    # .dmg, but it seems to apply to the entire set. So instead we'll store this
                    # as a hash so that we don't store duplicates and we don't give off the
                    # impression it's only for one file
                    with open(f"{root}/{file}", "rb") as f:
                        new_filename = hashlib.md5(f.read()).hexdigest()
                        shutil.copy(f"{root}/{file}", f"{key_dir}/{new_filename}.pem")

        if os.path.exists(key_dir) is False:
            # There were no keys obtained, create a file to indicate a successful attempt
            open(key_dir, "w").close()


def main():
    fcs = FCS_Downloader()
    fcs.update_keys()

    r = requests.get("https://api.appledb.dev/ios/index.json")
    r.raise_for_status()

    for entry in r.json():
        apple_os, build = entry.split(";", 1)
        if apple_os in SUPPORTED_OSES:
            match = re.match(r"(\d+)", build)
            if match:
                major = int(match.group(1))
                if major >= MIN_BUILD_VER:
                    download_build_keys(apple_os, build)


if __name__ == "__main__":
    main()
