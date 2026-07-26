# Security Policy

## Supported versions

Only the latest minor release receives security updates. Pin to the most
recent tag for production use.

## Reporting a vulnerability

Email **security@jordannewell.com** with:

- A description of the issue and its impact
- Reproduction steps (a minimal example is ideal)
- Affected version — run `harbormasterd --version`

**Do not open a public GitHub issue** for security reports.

## Response timeline

- **Acknowledgment:** within 72 hours
- **Initial assessment:** within 5 business days
- **Fix or mitigation:** target 30 days for high-severity issues

Please refrain from public disclosure until a fix has been published, to
protect downstream users. Reporters will be credited in the release notes
unless they prefer otherwise.

## Scope

**In scope:**

- The daemon (`harbormasterd` and its subcommands)
- Certificate management (mkcert integration)
- DNS handling

harbormasterd manages local TLS certificates, so any report about
certificate handling, key storage, or privilege escalation is treated as
high-priority.

**Out of scope:**

- mkcert itself — report upstream
- The local DNS server implementation
- OS-level networking