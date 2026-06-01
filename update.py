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
    _appledb_setup: bool = False

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

        if BuildIterator._appledb_setup is False:
            submodule_dir = Path(__file__).resolve().parent / "appledb"
            print(f"Checking for local appledb at: {submodule_dir}")
            print(f"  is_dir: {submodule_dir.is_dir()}, has osFiles: {(submodule_dir / 'osFiles').is_dir()}")
            if submodule_dir.is_dir() and (submodule_dir / "osFiles").is_dir():
                self.APPLEDB_DIR.parent.mkdir(parents=True, exist_ok=True)
                if self.APPLEDB_DIR.is_symlink() or self.APPLEDB_DIR.is_file():
                    self.APPLEDB_DIR.unlink()
                elif self.APPLEDB_DIR.is_dir():
                    shutil.rmtree(self.APPLEDB_DIR)
                print(f"Cloning {submodule_dir} -> {self.APPLEDB_DIR} (local shallow clone)...")
                subprocess.check_call([
                    "git", "clone", "--depth", "1",
                    f"file://{submodule_dir}", str(self.APPLEDB_DIR),
                ])
                os_dirs = list((self.APPLEDB_DIR / "osFiles").iterdir())
                print(f"Clone complete. osFiles contains: {[d.name for d in os_dirs if d.is_dir()]}")
            else:
                try:
                    print("No local appledb submodule found, downloading...")
                    args = ["ipsw", "dl", "appledb", "--os", "iOS", "--json"]
                    print(" ".join(args))
                    subprocess.check_output(args)
                except subprocess.CalledProcessError as e:
                    traceback.print_exc()
                    raise Exception("Failed to download appledb data, cannot continue") from e
            BuildIterator._appledb_setup = True

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
            prev_count = len(key_log)

            os_path = self.APPLEDB_DIR / "osFiles" / apple_os
            print(f"[{self.name}] Scanning {os_path} for {apple_os} builds...")
            new_builds = []
            for _root, _dirs, files in os.walk(os_path):
                for f in files:
                    if f.endswith(".json"):
                        appledb_found = True
                        buildid = f.rsplit(".", 1)[0]

                        if buildid not in key_log:
                            key_log[buildid] = 0
                            new_builds.append(buildid)

            pending = {k: v for k, v in key_log.items() if isinstance(v, int) and not isinstance(v, bool)}
            print(f"[{self.name}] {apple_os}: {len(key_log)} total builds ({len(key_log) - prev_count} new), {len(pending)} pending")
            if new_builds:
                print(f"[{self.name}] New builds: {new_builds}")

            for buildid in key_log:
                val = key_log[buildid]
                if isinstance(val, bool):
                    continue

                print(f"[{self.name}] Trying {buildid} for {apple_os}, attempt {val + 1}/{self.max_attempts}")
                try:
                    self.download(apple_os, buildid)
                    key_log[buildid] = True
                    print(f"[{self.name}] SUCCESS: {buildid} for {apple_os}")
                except Exception:
                    traceback.print_exc()
                    key_log[buildid] = val + 1
                    if key_log[buildid] >= self.max_attempts:
                        key_log[buildid] = False
                        print(f"[{self.name}] FAILED: {buildid} for {apple_os} (max attempts reached)")
                    else:
                        print(f"[{self.name}] RETRY: {buildid} for {apple_os} (attempt {key_log[buildid]}/{self.max_attempts})")

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
        fcs_path = Path("fcs-keys.json")
        before = fcs_path.read_bytes() if fcs_path.exists() else b""

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
            result = subprocess.run(args, capture_output=True, text=True)
            if result.stdout:
                print(f"[ipsw stdout] {result.stdout}")
            if result.stderr:
                print(f"[ipsw stderr] {result.stderr}")
            if result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, args)
        except Exception:
            traceback.print_exc()
            raise

        after = fcs_path.read_bytes() if fcs_path.exists() else b""
        if before == after:
            if "no results found for query" in result.stderr:
                print(f"No IPSW sources found for {apple_os} {buildid} (build may not have FCS keys for this OS)")
            else:
                raise Exception(f"ipsw exited 0 but fcs-keys.json was not modified for {apple_os} {buildid}")

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
                result = subprocess.run(args, capture_output=True, text=True)
                if result.stdout:
                    print(f"[ipsw stdout] {result.stdout}")
                if result.stderr:
                    print(f"[ipsw stderr] {result.stderr}")
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(result.returncode, args)

                found_pem = False
                for root, _dirs, files in os.walk(tempdir):
                    for file in sorted(files):
                        if file.endswith(".pem"):
                            found_pem = True
                            os.makedirs(key_dir, exist_ok=True)
                            with open(f"{root}/{file}", "rb") as f:
                                new_filename = hashlib.md5(f.read()).hexdigest()
                                print(f"Copying {file} to {key_dir}/{new_filename}.pem")
                                shutil.copy(f"{root}/{file}", f"{key_dir}/{new_filename}.pem")

                if not found_pem:
                    if "no results found for query" in result.stderr:
                        print(f"No IPSW sources found for {apple_os} {buildid} (build may not have keys for this OS)")
                    else:
                        raise Exception(f"ipsw exited 0 but no .pem files produced for {apple_os} {buildid}")
            except Exception:
                traceback.print_exc()
                raise


def main():
    try:
        ver = subprocess.check_output(["ipsw", "version"], stderr=subprocess.STDOUT).decode().strip()
        print(f"ipsw version: {ver}")
    except Exception as e:
        print(f"WARNING: Could not get ipsw version: {e}")

    print("Running FCS_Updater...")
    fcs_updater = FCS_Updater()
    fcs_updater.update()

    print("Running Key_Updater...")
    key_updater = Key_Updater()
    key_updater.update()

    print("Finished")


if __name__ == "__main__":
    main()
