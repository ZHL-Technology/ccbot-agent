# Changelog

All notable changes to CCBot Linux Agent are documented here.

The project follows semantic versioning.

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
