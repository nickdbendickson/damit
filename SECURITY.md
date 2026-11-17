# Security Policy

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue or pull
request.

Use GitHub's private vulnerability reporting for this repository:
**Security → Advisories → Report a vulnerability**
(<https://github.com/nickdbendickson/damit/security/advisories/new>).

Include the version or commit, which component (a plugin, `damit_crest`, or
`damit_ai`), the platform, and the steps to reproduce. You'll get an
acknowledgement, and a fix or an explanation of why it is not a problem. Please
do not publish details until a fix is available.

## Scope

DamIT is several components: the QGIS plugins (`damit_*`), the standalone Crest
desktop/web app (`damit_crest`), and the AI tools (`damit_ai`). Data a user
opens or imports — dam files, saved projects, offline packs, DSS-WISE packages,
shared records — is treated as untrusted input. Reports that matter most involve
code execution, reading or writing files outside a component's own folders, or
exposure of a local credential (e.g. the Crest desktop server's loopback token).

## Secrets

Never commit API keys, tokens, or other credentials. If one is exposed, rotate
it at the provider immediately — rotation, not deletion from git history, is what
makes an exposed credential safe.
