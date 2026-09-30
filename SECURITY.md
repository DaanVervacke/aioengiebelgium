# Security policy

## Reporting a vulnerability

Please use [GitHub's private vulnerability reporting](https://github.com/DaanVervacke/aioengiebelgium/security/advisories/new)
to report security issues. Do not open a public issue for a vulnerability.

## Credentials

Never paste tokens, passwords, MFA codes, or `Authorization` headers into
issues, pull requests, discussions, or reports. This includes values that look
expired. Redact them before sharing any request or response payload.

If you have already shared credentials publicly, rotate them: log out of the
ENGIE app or revoke the session, then log in again so fresh tokens are issued.

## Scope

This library talks to an unofficial, reverse-engineered API. Treat any response
from it as untrusted input, and report anything that looks like it could affect
users of the library.
