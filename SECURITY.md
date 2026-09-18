# Security Policy

ActWise is an **unofficial, experimental (beta)** toolkit provided **as-is, without
warranty**. Even so, we take security seriously and appreciate responsible
disclosure.

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Instead, report privately via GitHub's
[private vulnerability reporting](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository ("Security" tab → "Report a vulnerability"). If that is
unavailable, open a minimal issue that says only "requesting a private security
contact" — with **no details** — and a maintainer will follow up.

When reporting, please include:

- A description of the issue and its impact.
- Steps to reproduce (using **synthetic** data only — never real credentials or
  customer/production data).
- Affected version(s) and environment.

We aim to acknowledge reports within a few business days and to coordinate a fix and
disclosure timeline with you.

## Scope

This policy covers the ActWise code in this repository (CLIs, MCP servers, skills,
and the export tooling). It does **not** cover:

- NICE Actimize products or infrastructure — report those to NICE through their
  official channels; ActWise is not affiliated with NICE.
- Third-party dependencies — report those to their respective maintainers.
- Any self-hosted deployment you operate; you are responsible for securing your own
  endpoints, credentials, and network exposure.

## Handling secrets

ActWise is designed to keep secrets out of the repository: credentials, cookies, and
endpoint identifiers live only in local, gitignored files. If you believe a secret
or proprietary identifier has been committed, please report it privately as above so
we can rotate/remove it.
