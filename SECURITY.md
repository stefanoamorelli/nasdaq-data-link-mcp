# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 2.x | Yes |
| 1.0 and 0.x | No. They call APIs that Nasdaq has retired; upgrade to 2.x. |

## Reporting a vulnerability

Report vulnerabilities privately; do not open a public issue.

- GitHub: [report a vulnerability](https://github.com/stefanoamorelli/nasdaq-data-link-mcp/security/advisories/new)
  through private vulnerability reporting.
- Email: `stefano@amorelli.tech`.

Include the version (`nasdaq-data-link-mcp --version`), how the server was run
(stdio, HTTP, Docker), and the steps or the tool call that show the problem.
Never include a real API key; a placeholder is enough.

You will get an acknowledgement within 7 business days. Confirmed issues are
fixed within 90 days, sooner for severe ones, and published as a GitHub
security advisory (with a CVE where one applies) together with the release
that fixes them. Reporters are credited unless they ask not to be.

## Scope

In scope: this repository's code, its PyPI package (`nasdaq-data-link-mcp-os`)
and its Docker image (`stefanoamorelli/nasdaq-data-link-mcp`). Examples of
what we want to hear about:

- any way the Nasdaq Data Link API key reaches a tool result, an error
  message, a log line, a URL or a host other than `NDL_BASE_URL`;
- a statement that gets past the read-only guard of `ndl_sql_query`, or reads
  session or system information through it;
- a way to call the HTTP transports without `NDL_HTTP_TOKEN`, or to bind a
  non-loopback address without one;
- a `.env` file or other untrusted input that changes where requests go;
- files in the Docker image that should not be there.

Out of scope: Nasdaq Data Link itself and Nasdaq's own MCP server (report
those to Nasdaq), the accuracy of third-party data, and rate limits.

## How the API key is handled

- It is read from `NASDAQ_DATA_LINK_API_KEY` in the environment, from `.env`
  in the working directory, or from the file passed with `--env-file`.
- It is sent only to `NDL_BASE_URL` (default `https://data.nasdaq.com`): in
  the `X-Api-Token` header for the Tables API and as the Trino user header for
  DataLink SQL. It never appears in a URL. `NDL_BASE_URL` must be a bare
  `https://` origin and cannot be set from a `.env` file.
- The server does not log it, and removes it from every tool result and error
  message, including reversed, case-changed, hex and base64 forms.
- `ndl_sql_query` blocks `current_user`, `session_user`, `current_groups` and
  the `system` catalog, because Trino reports the key as the session user.
- In HTTP mode every caller spends the server's key, so any non-loopback bind
  requires a bearer token (`NDL_HTTP_TOKEN`).

## Known issues in old releases

The `v0.2.1` Docker image (`stefanoamorelli/nasdaq-data-link-mcp:v0.2.1`, also
tagged `latest` until 2.0.0) was built with `COPY . .` and no `.dockerignore`,
so it contains the files of the build directory, including `.env`, `.secrets`
and `.git`. Do not use it. Images built from a checkout of 0.2.1 to 1.0.0 have
the same problem with the builder's own files; rebuild them from 2.x and
rotate any key that was in the build directory.

## Secure development practices

This project follows the Tallinn Secure Software Practices for OSS, a baseline
from the [OWASP Tallinn Chapter](https://owasp.org/www-chapter-tallinn):

- **Secrets:** never commit secrets; use environment variables or a secret
  manager. `.env` and `.secrets` are ignored by git and excluded from the
  Docker build context, and a pre-commit hook rejects private keys.
- **Dependencies:** dependencies are locked in `uv.lock`, base images and
  GitHub Actions are pinned by digest or commit SHA, and Dependabot proposes
  updates after a cooldown.
- **Code review:** changes go through pull requests with review and passing
  CI; the main branch is protected.
- **CI/CD:** builds run in ephemeral runners with least-privilege tokens.
  PyPI uploads use Trusted Publishing (no stored token), and the PyPI and
  Docker Hub release jobs run in the `pypi` and `dockerhub` GitHub
  environments, which require a reviewer's approval.
- **Commits:** contributors use verified identities and sign their commits
  (GPG, SSH or GitHub's web UI); unsigned or anonymous commits may be
  rejected. See GitHub's documentation on
  [commit signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification).
- **Accounts:** enable two-factor authentication on GitHub and on any service
  with elevated access to the project.

References: [OWASP Secure Coding Practices](https://owasp.org/www-project-secure-coding-practices/),
[OpenSSF Best Practices](https://openssf.org/best-practices/),
[GitHub security features](https://docs.github.com/en/code-security),
[disclose.io safe harbor](https://disclose.io/).
