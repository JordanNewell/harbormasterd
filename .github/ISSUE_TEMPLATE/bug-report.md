---
name: Bug Report
about: Report a bug in harbormasterd to help us improve
title: "[BUG] "
labels: ["bug", "triage"]
assignees: []
---

## Bug description

A clear description of what's broken.

## Steps to reproduce

1.
2.
3.

## Expected behavior

What you thought would happen.

## Actual behavior

What actually happened.

## Daemon logs

Paste the relevant `harbormasterd` log output. **Sanitize first** — strip any TLS private keys, certificate material, hostnames, or credentials. Redact with `***` if uncertain.

```
paste sanitized log output here
```

## Environment

- **mkcert installed:** yes / no (output of `mkcert -version` if installed)n- **Cert store path / OS-specific cert location:** (e.g., `/etc/ssl/certs/ca-certificates.crt` on Linux, `/usr/local/share/ca-certificates` on macOS via mkcert, Windows cert store path)
- **Install source:** (PyPI / git checkout / distribution package)

## Logs / screenshots

Any additional context, screenshots, or `journalctl` output (sanitized).

## Self-check

- [ ] I have searched existing issues for duplicates.
- [ ] I have sanitized any TLS private keys, certificates, and credentials.
- [ ] This is not a security issue (those go through [SECURITY.md](../blob/master/SECURITY.md) privately).