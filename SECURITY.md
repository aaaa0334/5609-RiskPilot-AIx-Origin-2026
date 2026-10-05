# Security and privacy

## Secrets

RiskPilot reads optional model credentials from environment variables. Never commit real API keys, access tokens, passwords, private keys, wallet recovery phrases, `.env` files or credential exports.

Use `.env.example` only as a list of supported variable names. Store real values in the local process environment or the deployment provider's secret manager.

## Reporting

If you discover a security or privacy issue, open a GitHub issue containing only non-sensitive reproduction information. Do not paste credentials, private data or exploitable production details into a public issue.

## Product boundary

This repository is an educational prototype. It does not connect to brokerage accounts, hold user funds or execute trades.