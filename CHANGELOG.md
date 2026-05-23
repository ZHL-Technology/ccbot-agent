# Changelog

All notable changes to CCBot Agent are documented here.

The project follows semantic versioning.

## Unreleased

### Added

- Added GPU diagnostics to agent evidence, including NVIDIA `nvidia-smi`
  status, driver mismatch errors, basic PCI display-device hints on Linux, and
  Windows video-controller inventory.
- Added a versioned audit checklist to every agent report, with coverage
  status for identity, resources, ports, services, updates, certificates, GPU,
  firewall, authentication, privileged accounts, scheduled work, containers,
  logs, time sync, backups, kernel network policy, and endpoint protection.

## 0.1.8 - 2026-05-19

### Changed

- Windows installer now falls back to current-user Startup registration when
  Windows blocks scheduled task creation with access denied.

## 0.1.7 - 2026-05-19

### Changed

- Enrollment token failures now explain whether the token should be replaced
  instead of showing only the raw API payload.

## 0.1.6 - 2026-05-14

### Changed

- Windows installer failures now open a copyable error dialog and exit through
  an explicit Exit installer action.
- Added a Copy log button to the Windows installer.
- Agent API requests now send a CCBot User-Agent and return clearer guidance
  when Cloudflare blocks enrollment with Error 1010.

## 0.1.5 - 2026-05-14

### Changed

- Published a versioned Windows installer filename alongside the stable
  installer filename to avoid Windows Explorer showing a cached icon from an
  older download.

## 0.1.4 - 2026-05-14

### Changed

- Rebuilt the Windows installer icon as a multi-size Windows ICO for better
  File Explorer display.
- Moved the Windows installer action button above the log area so it stays
  visible after the token is pasted and the terms are accepted.

## 0.1.3 - 2026-05-14

### Changed

- Added the CCBot brand icon to the Windows installer executable, title bar,
  and taskbar identity.
- Added an explicit Paste button and right-click paste menu for the install
  token field.
- Added an optional GitHub Actions code-signing step for tagged Windows
  releases when a production signing certificate is configured.

## 0.1.2 - 2026-05-14

### Changed

- Improved the Windows installer preview with an agreement checkbox, visible
  progress bar, installation log, and clear Finish state.
- Windows enrollment errors now remain visible in the installer instead of
  failing silently in the background.

## 0.1.1 - 2026-05-14

### Added

- Windows installer preview with a small token-entry setup window.
- GitHub Actions build job for `CCBot-Windows-Installer.exe`.
- Basic Windows heartbeat support for disk usage and listening-port evidence.

### Changed

- Project metadata now describes the broader CCBot Agent package instead of
  only the Linux agent.

## 0.1.0 - 2026-05-12

Initial public preview foundation.

### Added

- One-time enrollment token exchange with CyberCare AI.
- Agent bearer-token storage after enrollment.
- Heartbeat submission with system health evidence.
- Daily report submission.
- Disk, memory, load, failed systemd unit, listening port, package update, and
  certificate expiry checks.
- systemd installer for common Linux distributions.
- Dedicated `ccbot-agent` system user.
- Versioned installer and release workflow documentation.
