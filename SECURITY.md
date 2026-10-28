# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Email inboxpraveen.17@gmail.com with what you found, the version or commit, and the steps to reproduce it. I will reply as soon as I can and credit you in the changelog if you want.

## Supported versions

Fixes go into the latest 3.x release on `master`. Versions 1.x and 2.x are not maintained.

## Before you deploy

The defaults suit a laptop or a trusted network. For a shared server see [Running it for a team](docs/setup.md#running-it-for-a-team). In short:

- The first account is `admin` / `admin`. Change it. The app logs a warning at every start while it is unchanged.
- The app serves plain HTTP. Put a reverse proxy with TLS in front and set `COOKIE_SECURE=true`.
- There is no login rate limiting. Add one at the proxy if the app is reachable from outside your network.
- Every signed-in user can browse the folders the server account can read and create projects on them. In Docker the host files it can reach are limited to the folders you mount.
- Provider API keys and the Hugging Face token are stored as plain text in `data/app.db`. Restrict access to the `data/` folder and do not commit it.
- Uploads (import files) are limited to 2 GB per request.
