# Security policy

## Supported version

Security fixes are applied to the latest version on the default branch.

## Reporting a vulnerability

When GitHub private vulnerability reporting is available for this repository,
please use that form. Until then, contact the maintainer through a private
channel listed on their GitHub profile. Do not publish API keys, OAuth
credentials, learner content, local data paths or a working exploit in a public
issue.

Include the affected version, operating system, reproduction steps and the
security boundary involved. Relevant boundaries include the loopback service,
launch/session tokens, CSRF protection, registered media access, provider
credentials, privacy consent and Session persistence.

## Local data model

言蹊 (Yanxi) is a local single-user application. The service binds to
`127.0.0.1`, learning data lives outside the installation directory and model
credentials are stored outside SQLite. Users remain responsible for securing
their operating-system account and for importing only material they are
entitled to use.
