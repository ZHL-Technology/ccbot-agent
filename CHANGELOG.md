# Changelog

All notable changes to CCBot Agent are documented here.

The project follows semantic versioning.

## Unreleased

## 0.1.14 - 2026-06-09

### Added

- Added a Windows notification-area tray icon for CCBot Agent.
- Added a local status window with version number, bot state, last heartbeat,
  last report, operating system, install path, and last error.
- Added tray actions for manual update checks and pausing or resuming CCBot
  monitoring.

## 0.1.13 - 2026-06-09

### Changed

- Published a test release for validating the Windows background update prompt
  and self-update flow from CCBot Agent 0.1.12.

## 0.1.12 - 2026-06-09

### Added

- Windows background agent now checks the CyberCare AI update manifest while it
  is running and prompts the user when a newer release is available.
- Added a small background update progress window so user-approved updates can
  download, replace the installed executable, and restart CCBot without opening
  the installer manually.
- Added update prompt cooldown state to avoid repeatedly asking the user about
  the same release.

## 0.1.11 - 2026-06-09

### Changed

- Windows installer now shows a friendly retry dialog when the enrollment token
  is invalid, expired, already used, or revoked.
- Invalid-token failures now clear the token field and return the user to the
  installer instead of forcing them to exit.
- Technical traceback details are hidden for token failures and kept only for
  support-oriented installation or update errors.

## 0.1.10 - 2026-06-09

### Added

- Windows installer now displays the installed CCBot Agent version in the app.
- Windows installer now checks the CyberCare AI update manifest for newer
  releases and prompts the user before downloading an update.
- Added a self-update path for Windows that replaces the installed executable,
  refreshes startup registration, and restarts the background agent without
  asking for a new enrollment token.

## 0.1.9 - 2026-06-05

### Added

- Added GPU diagnostics to agent evidence, including NVIDIA `nvidia-smi`
  status, driver mismatch errors, basic PCI display-device hints on Linux, and
  Windows video-controller inventory.
- Added a versioned audit checklist to every agent report, with coverage
  status for identity, resources, ports, services, updates, certificates, GPU,
  firewall, authentication, privileged accounts, scheduled work, containers,
  logs, time sync, backups, kernel network policy, and endpoint protection.

### Changed

- Agent API requests now handle DNS, timeout, and network failures as retryable
  errors instead of crashing the Windows background monitor.
- Daily reports are only marked as delivered after a successful platform
  response.
- The long-running agent loop now logs unexpected runtime errors and continues
  monitoring instead of showing an unhandled exception popup.

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
