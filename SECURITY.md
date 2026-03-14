# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | YES       |
| < 1.0   | No        |

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Email: security@saluca.com

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact assessment
- Your name/handle for attribution (optional)

We will acknowledge receipt within 48 hours and provide a timeline for a fix.
Confirmed vulnerabilities receive a CVE and public disclosure after patch release.

## Scope

In scope:
- Tiresias proxy server (request interception, token handling)
- Encryption module (DEK/KEK management, BYOK integrations)
- License validation logic
- Dashboard authentication

Out of scope:
- Third-party LLM provider security
- Infrastructure you deploy Tiresias on
- Issues in dependencies (report to upstream)

## Dependency Audit

The `tiresias-core` module has been audited for telemetry/beaconing libraries.
No third-party analytics, crash reporting, or data exfiltration dependencies
are included. All external calls are user-initiated proxy requests to configured
upstream providers.
