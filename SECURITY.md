# Security and privacy

This tool reads local session histories and account configuration. Treat it as sensitive local tooling, not as a security sandbox between mutually untrusted accounts.

- Never commit `auth.json`, access/refresh tokens, API keys, account configurations, rollouts, SQLite databases, production logs, or backups.
- Imported conversation history can become context for the target account/provider when the user continues a session. Only import material you are authorized to send there.
- Account homes and credentials must remain accessible only to the intended operating-system user. The wrapper requests file-based credential storage; it does not encrypt credentials or add an OS-level isolation boundary.
- Shared instruction/skill/rule symlinks expose those files to account sessions. Review the shared content and avoid treating account names as permission boundaries.
- Use trusted local filesystems and a common coordination lock directory. Do not assume these locks synchronize separate hosts or prevent direct native clients from writing separate copies.
- Refusal on divergent history protects against data loss. Do not resolve it by deleting the shorter file, blindly choosing a timestamp, or removing an active lock.
- Back up important histories before upgrades. Protocol compatibility must be retested against actual CLI/app-server versions.

Do not publish real credentials, private conversation excerpts, or other sensitive details in issues. For reports that require private details, use GitHub private vulnerability reporting when it is available for this repository. If it is unavailable, open a minimal issue requesting a private contact channel without including the sensitive material.
