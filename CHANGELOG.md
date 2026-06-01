# Changelog

## 2026-06-01 (2)

### Fixed
- FCS key validation false failures when iPadOS/iOS share the same keys
- ipsw now writes to a temp file; keys are merged into the master `fcs-keys.json` so duplicates are handled silently

## 2026-06-01

### Fixed
- Key extraction broken since May 12 refactor: symlink to appledb submodule caused ipsw's internal git refresh to fail silently
- Replaced symlink with local shallow clone (`git clone --depth 1 file://...`) so ipsw gets a proper git repo
- Added output validation: FCS_Updater verifies `fcs-keys.json` was modified, Key_Updater verifies `.pem` files were produced
- Builds with no IPSW sources for a given OS (e.g. iPadOS-only builds) now pass validation correctly
- Reset 8 falsely-marked builds across tracking JSONs for retry

### Changed
- Capture and print ipsw stdout/stderr for easier debugging
- Log ipsw version, build discovery counts, and per-build success/retry/fail status
