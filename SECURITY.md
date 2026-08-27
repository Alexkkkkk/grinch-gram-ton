# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 3.1.x   | :white_check_mark: |
| 3.0.x   | :x:                |
| 2.x     | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please **DO NOT** open a public issue.

Instead, report it privately via:

- Email: **security@grinch-gram.local**
- GitHub Security Advisory: [Report here](https://github.com/Alexkkkkk/grinch-gram-ton/security/advisories/new)

We will respond within 48 hours and work with you to assess and address the issue.

## Security Measures

- All dependencies are scanned with Dependabot
- Docker images run as non-root user (`bot`)
- No secrets are baked into Docker images
- `.env` files are excluded from version control
- Bandit security linter runs in CI

## Known Security Considerations

- **TON Mnemonic**: Stored in environment variable. Never commit to git.
- **API Keys**: Use `.env` or Docker secrets. Rotate regularly.
- **Wallet Access**: The bot has full control of the configured TON wallet.
  Use a dedicated wallet with limited funds.
