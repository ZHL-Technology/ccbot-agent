# CCBot Agent

CCBot Agent is the installable monitoring agent for CyberCare AI. The Linux
agent runs as a managed service today, and the Windows installer preview gives
desktop and Windows Server users a simple token-based setup path.

Current version: `0.1.6`

Status: preview foundation. The agent is ready for controlled testing and will
continue to evolve with signed releases, stronger policy controls, and deeper
remediation workflows.

## Why This Agent Exists

Servers rarely become risky because of one dramatic event. Risk usually grows
quietly: disks fill up, services fail, certificates expire, packages age, ports
stay open after old work, and administrators lose visibility across machines.

CCBot is designed to give that visibility back. The agent checks the server
continuously and sends structured evidence to CyberCare AI so users can see
what changed, what needs attention, and what should be verified before any
cleanup or remediation work is approved.

## Trust Model

The agent source is public so administrators can inspect what runs on their
servers.

Activation is private. A downloaded copy cannot enroll, monitor, or submit
reports unless the user has:

- An active CyberCare AI plan that includes CCBot Agent monitoring.
- A one-time enrollment token generated inside the CyberCare AI dashboard.
- Network access from the monitored device to the CyberCare AI platform.

The enrollment token is exchanged for an agent token during setup and then
removed from the local config file.

## What CCBot Collects

The preview agent focuses on system health and security hygiene signals:

- Hostname, OS, kernel, Python version, and machine identity.
- Load average, memory status, and swap status.
- Disk usage for real filesystems.
- Failed `systemd` units.
- Listening TCP/UDP ports from `ss`.
- Available package update hints for common package managers.
- Certificate expiry hints under common Let's Encrypt paths.

The agent does not scan application databases, does not read arbitrary user
files, and does not execute cleanup actions in this preview version. Collected
command output can still include hostnames, local paths, service names, package
names, usernames, and process metadata, so treat reports as operationally
sensitive.

## Supported Platforms

The installer can prepare prerequisites on common distributions:

- Debian / Ubuntu
- RHEL / Rocky Linux / AlmaLinux / CentOS
- Fedora
- SUSE / openSUSE
- Arch Linux

The runtime only requires Python 3, `curl`, certificates, OpenSSL, `systemd`,
and `ss` from the iproute package family.

Windows support is available as an installer preview. The Windows executable
opens a setup window, accepts the one-time install token, asks the user to
accept the monitoring terms, shows installation progress, enrolls the device,
and starts CCBot in the background for the signed-in user.

## Install

Create a one-time install token in CyberCare AI first. Then run the commands
below on the Linux server you want to monitor.

Use a pinned release tag for repeatable installs:

```bash
export CCBOT_PLATFORM_URL="https://cybercareai.io"
export CCBOT_ENROLLMENT_TOKEN="PASTE_ONE_TIME_TOKEN_HERE"
export CCBOT_AGENT_VERSION="v0.1.6"

curl -fsSL "https://raw.githubusercontent.com/ZHL-Technology/ccbot-agent/${CCBOT_AGENT_VERSION}/install.sh" -o /tmp/ccbot-agent-install.sh
sudo CCBOT_PLATFORM_URL="$CCBOT_PLATFORM_URL" CCBOT_ENROLLMENT_TOKEN="$CCBOT_ENROLLMENT_TOKEN" bash /tmp/ccbot-agent-install.sh
```

Do not paste enrollment tokens into tickets, chat logs, screenshots, or shell
history that other people can read.

## Windows Installer Preview

The Windows installer is built by GitHub Actions as:

```text
CCBot-Windows-Installer.exe
```

Download path for tagged releases:

```text
https://github.com/ZHL-Technology/ccbot-agent/releases/download/v0.1.6/CCBot-Windows-Installer-v0.1.6.exe
```

The installer asks for:

- CyberCare AI platform URL, normally `https://cybercareai.io`
- One-time install token from the CyberCare AI CCBot page

After enrollment it creates a Windows scheduled task named `CCBot Agent` and
starts the background monitor. The preview installer shows a visible install
button, progress bar, installation log, CCBot branding, and a Paste button for
the token field so enrollment or startup errors are visible to the user.

This preview is intended to remove terminal work from the normal Windows user
path. Windows SmartScreen may warn that the first preview builds are
unrecognized until a production code-signing certificate is added and the app
builds reputation with Microsoft. The release workflow supports optional
certificate signing through GitHub secrets; only run installers downloaded from
the official CyberCare AI GitHub release.

## Verify Installation

```bash
sudo systemctl status ccbot-agent --no-pager
```

```bash
sudo journalctl -u ccbot-agent -n 80 --no-pager
```

```bash
sudo python3 /opt/ccbot-agent/ccbot-agent.py collect
```

## Files And Paths

The installer creates the following local paths:

```text
/opt/ccbot-agent/ccbot-agent.py        Agent runtime
/etc/ccbot-agent/config.json           Platform URL and runtime settings
/var/lib/ccbot-agent/state.json        Agent ID, agent token, report state
/etc/systemd/system/ccbot-agent.service systemd service
```

The service runs as the dedicated `ccbot-agent` system user.

## Configuration

Default config:

```json
{
  "platform_url": "https://cybercareai.io",
  "heartbeat_seconds": 300,
  "report_every_seconds": 86400,
  "state_path": "/var/lib/ccbot-agent/state.json"
}
```

Useful settings:

- `platform_url`: CyberCare AI platform URL.
- `heartbeat_seconds`: How often the agent sends heartbeat health data.
- `report_every_seconds`: How often the agent sends a full periodic report.
- `state_path`: Where the enrolled agent token and report state are stored.

Keep `/etc/ccbot-agent/config.json` and `/var/lib/ccbot-agent/state.json`
readable only by root and the `ccbot-agent` service user.

## Agent Commands

Run a local collection without sending data:

```bash
python3 -m ccbot_agent.main collect
```

Enroll using a custom config:

```bash
python3 -m ccbot_agent.main enroll --config ./config.json
```

Run the foreground monitor:

```bash
python3 -m ccbot_agent.main run --config ./config.json
```

Show the installed version:

```bash
python3 -m ccbot_agent.main --version
```

## Upgrade

For a controlled upgrade, choose the release tag explicitly:

```bash
export CCBOT_AGENT_VERSION="v0.1.6"
curl -fsSL "https://raw.githubusercontent.com/ZHL-Technology/ccbot-agent/${CCBOT_AGENT_VERSION}/install.sh" -o /tmp/ccbot-agent-install.sh
sudo CCBOT_PLATFORM_URL="https://cybercareai.io" CCBOT_ENROLLMENT_TOKEN="PASTE_ONE_TIME_TOKEN_HERE" bash /tmp/ccbot-agent-install.sh
```

The preview installer re-enrolls when a new one-time token is supplied. A later
release will add a dedicated upgrade path that preserves enrollment without
requiring a new token.

## Uninstall

```bash
sudo systemctl disable --now ccbot-agent || true
sudo rm -f /etc/systemd/system/ccbot-agent.service
sudo systemctl daemon-reload
sudo rm -rf /opt/ccbot-agent /etc/ccbot-agent /var/lib/ccbot-agent
sudo userdel ccbot-agent 2>/dev/null || true
```

Remove the server entry from CyberCare AI after uninstalling so stale agents do
not remain in the dashboard.

## Versioning

CCBot Agent uses semantic versioning:

```text
MAJOR.MINOR.PATCH
```

- Patch releases fix bugs without changing expected behavior.
- Minor releases add compatible features or new checks.
- Major releases may change enrollment, configuration, API contracts, or
  operating behavior.

Version data is kept in:

- `VERSION`
- `pyproject.toml`
- `ccbot_agent/__init__.py`
- `install.sh`
- Git tags such as `v0.1.6`

To prepare a future version:

```bash
python3 scripts/bump_version.py 0.1.6
```

Then update `CHANGELOG.md`, commit the change, and create a signed or annotated
release tag:

```bash
git tag -a v0.1.6 -m "CCBot Agent v0.1.6"
git push origin main --tags
```

## Development

Run from a local checkout:

```bash
python3 -m ccbot_agent.main --version
python3 -m ccbot_agent.main collect
```

Run a syntax check:

```bash
python3 -m compileall ccbot_agent
```

Build a local package:

```bash
python3 -m build
```

## API Flow

The agent talks to CyberCare AI over HTTPS:

1. `POST /api/agents/enroll/`
2. `POST /api/agents/heartbeat/`
3. `POST /api/agents/reports/`

Heartbeat and report requests use the enrolled agent token as a bearer token.

## Security Notes

- Only install the agent on servers you own or are authorized to administer.
- Review `install.sh` before running it in production.
- Keep enrollment tokens short-lived and private.
- Store screenshots and logs carefully because they may contain host metadata.
- Prefer pinned release tags over unpinned `main` installs.

## License

No open source license has been published for this preview release. Until a
license is added, all rights are reserved by ZHL Technology.
