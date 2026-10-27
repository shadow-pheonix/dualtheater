# Network and report privacy

DualTheater is an experimental trusted-LAN application. Its control and media traffic are not encrypted. Do not expose its ports directly to the Internet or use it on an untrusted network.

Keep pairing state, local configuration, calibration, logs and signing keys out of source control. `.gitignore` excludes the usual runtime files; it cannot sanitize files that have already been committed. Review staged content before publishing.

Before attaching diagnostics to a public issue, remove network addresses, user directories, file/media names, endpoint identifiers, pairing codes and credentials. Prefer a short sanitized description or minimal excerpt. Never upload private keys, full media files or raw personal logs.

Do not put sensitive vulnerability details in a public issue. Use GitHub's private reporting option if the repository enables it; otherwise request a private reporting channel without including the sensitive details.
