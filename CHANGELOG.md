# Changelog

All notable changes to CCBot Agent are documented here.

The project follows semantic versioning.

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
