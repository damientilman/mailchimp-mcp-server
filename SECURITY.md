# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in `mailchimp-mcp`, please report it
**privately** so it can be addressed before public disclosure.

**Email:** damien@tilman.marketing

Please include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce, including any proof-of-concept code.
- The version of `mailchimp-mcp` affected.
- Any suggested mitigation or fix.

You will receive an acknowledgement within **5 business days**. The maintainer will
investigate, communicate a timeline, and coordinate disclosure with you.

Please **do not** open a public GitHub issue for security vulnerabilities, post about
them on social media, or share them with third parties before they have been addressed.

## Supported Versions

Security fixes are applied to the latest minor release. Older releases are not
maintained.

| Version | Supported |
| ------- | --------- |
| 0.2.x   | Yes       |
| < 0.2   | No        |

## Scope

This policy covers the `mailchimp-mcp` package and its source code in this repository.
It does **not** cover:

- Vulnerabilities in the Mailchimp Marketing API itself (report those to
  [Mailchimp Security](https://mailchimp.com/about/security/)).
- Vulnerabilities in third-party dependencies (report those upstream).
- Issues caused by misconfiguration of the deploying environment.

## Handling Credentials

This server requires a Mailchimp API key, which grants full access to a Mailchimp
account. Users are responsible for:

- Keeping their API key secret (never commit it to source control).
- Rotating keys regularly and revoking compromised keys via the Mailchimp dashboard.
- Running the server in `MAILCHIMP_READ_ONLY=true` mode whenever write access is not
  required.

If you find a way this server could leak or mishandle credentials, please report it
under the policy above.
