# Security

This application is meant to run on your own machine, for your own use. You are
encouraged to read the source code and verify it before trusting it with your data — the
license explicitly permits inspecting and test-running the code for security review.

## Good practices when deploying

- Keep `SECRET_KEY` secret (it signs login sessions). `setup.sh` generates a strong one.
- Change `POSTGRES_PASSWORD` if the database is reachable from anything other than the
  local machine. By default it is bound to `127.0.0.1` only.
- The app binds to `localhost` by default. If you expose it on a network, put it behind a
  reverse proxy that terminates HTTPS, and consider restricting access to a private
  VPN/LAN.
- Never commit your `.env` file or the `backups/` folder to source control (they are
  already in `.gitignore`).

## Reporting a vulnerability

If you find a security issue, please report it privately rather than opening a public
issue:

- Email: **k.bonikos@protonmail.ch**

Please include steps to reproduce and the affected version/commit. Thank you for helping
keep users safe.
