# Security policy

FlagshipOS is a rootless environment manager. Its trust boundary is the host user account, not a hardened sandbox for hostile samples. It uses official image references, verifies supplied import checksums, avoids shell evaluation of user commands, and requires matching ownership metadata before managing a container.

Report defects in FlagshipOS itself through GitHub's private vulnerability reporting feature when available. If it is unavailable, open a minimal issue asking for a private contact without including sensitive details. Report vulnerabilities in upstream tools or images to their maintainers.

Never attach credentials, personal root filesystems, challenge secrets or private data to an issue. Provide a minimal reproduction with harmless local fixtures, the FlagshipOS version, Ubuntu/WSL versions and sanitized diagnostics.

Only the latest published FlagshipOS version receives maintenance. No claim is made that the upstream security tool collections are free of vulnerabilities.
