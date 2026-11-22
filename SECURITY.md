# Security Policy

Universal Backup is currently an alpha project. Do not assume it is suitable as the sole copy of important data.

## Supported versions

Security fixes are currently targeted at the latest release on the default branch.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting feature for this repository when enabled. Do not include credentials, private files, backup archives, or personal identifiers in public issues.

## Security boundaries

Universal Backup currently does not provide encryption-at-rest, remote access, cloud credential management, or privilege separation for untrusted multi-user environments. Job YAML files are executable backup policy and should only be writable by trusted local users. Keep configuration and backup destinations access-controlled.
