#! /usr/bin/env python3

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import traceback

from abc import ABC, abstractmethod
from pathlib import Path
from typing import override


class BuildIterator(ABC):
    _appledb_present: bool = False

    def __init__(
        self,
        name: str,
        max_attempts: int = 10,
        oses: list[str] | None = None,
    ):
        self.APPLEDB_DIR = Path("~/.config/ipsw/appledb").expanduser()
        print(f"Using appledb directory: {self.APPLEDB_DIR}")

        SUPPORTED_OSES = ["iOS", "iPadOS", "macOS"]
        if oses is None:
            oses = SUPPORTED_OSES
        self.name = name
        self.max_attempts = max_attempts
        self.oses = oses

        if BuildIterator._appledb_present is False:
            try:
                print("Downloading appledb data...")
                args = ["ipsw", "dl", "appledb", "--os", "iOS", "--json"]
                print(" ".join(args))
                subprocess.check_output(args)
                BuildIterator._appledb_present = True
            except subprocess.CalledProcessError as e:
                traceback.print_exc()
                raise Exception("Failed to download appledb data, cannot continue") from e

    def _load_keylog(self, apple_os: str) -> dict[str, int | bool]:
        # Format is
        # {buildid: bool if success/fail, otherwise int for number of attempts}

        key_log: dict[str, int | bool] = {}
        try:
            with open(f"{apple_os}_{self.name}.json") as f:
                key_log = json.load(f)
        except FileNotFoundError:
            pass
        return key_log

    def _save_keylog(self, apple_os: str, key_log: dict[str, int | bool]):
        with open(f"{apple_os}_{self.name}.json", "w") as f:
            json.dump(key_log, f, sort_keys=True, indent=2)

    def update(self):
        appledb_found = False

        for apple_os in self.oses:
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

                print(f"Trying {buildid} for {apple_os}, attempt {val + 1}/{self.max_attempts}")
                try:
                    self.download(apple_os, buildid)
                    key_log[buildid] = True
                except Exception:
                    traceback.print_exc()
                    key_log[buildid] = val + 1
                    if key_log[buildid] >= self.max_attempts:
                        key_log[buildid] = False

                # Save immediately on mutate
                self._save_keylog(apple_os, key_log)

        if appledb_found is False:
            raise Exception(f"No appledb data found in {self.APPLEDB_DIR}")

        self.cleanup()

    @abstractmethod
    def download(self, apple_os: str, buildid: str): ...

    def cleanup(self):
        pass


class FCS_Updater(BuildIterator):
    def __init__(self):
        super().__init__("fcs")

    @override
    def download(
        self,
        apple_os: str,
        buildid: str,
    ):
        try:
            args = [
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
            print("Running FCS key download:")
            print(" ".join(args))
            subprocess.check_call(args)
        except Exception:
            traceback.print_exc()

    @override
    def cleanup(self):
        # Sort fcs-keys to make it easier for the git commit, but also for human eyes
        with open("fcs-keys.json", "r") as f:
            all_keys = json.load(f)
        with open("fcs-keys.json", "w") as f:
            json.dump(all_keys, f, sort_keys=True, indent=2)


class Key_Updater(BuildIterator):
    def __init__(self):
        super().__init__("key")
        self.KEYS_DIR = "keys"

    @override
    def download(
        self,
        apple_os: str,
        buildid: str,
    ):
        os_dir = f"{self.KEYS_DIR}/{apple_os}"
        key_dir = f"{os_dir}/{buildid}"

        with tempfile.TemporaryDirectory() as tempdir:
            try:
                print(f"Downloading keys for {apple_os} {buildid} to {tempdir}")
                args = [
                    "ipsw",
                    "dl",
                    "appledb",
                    "--os",
                    apple_os,
                    "--build",
                    buildid,
                    "--fcs-keys",
                    "--output",
                    tempdir,
                    "--confirm",
                ]
                print(" ".join(args))
                subprocess.check_call(args)

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
                                print(f"Copying {file} to {key_dir}/{new_filename}.pem")
                                shutil.copy(f"{root}/{file}", f"{key_dir}/{new_filename}.pem")
            except Exception:
                traceback.print_exc()


def main():
    print("Running FCS_Updater...")
    fcs_updater = FCS_Updater()
    fcs_updater.update()

    print("Running Key_Updater...")
    key_updater = Key_Updater()
    key_updater.update()

    print("Finished")


if __name__ == "__main__":
    main()
