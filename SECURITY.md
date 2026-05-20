# Security Policy

## Supported Versions

We release patches for security vulnerabilities for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to: security@ytnotes.co

You should receive a response within 48 hours. If for some reason you do not, please follow up via email to ensure we received your original message.

Please include the following information:

- Type of issue (e.g. buffer overflow, SQL injection, cross-site scripting, etc.)
- Full paths of source file(s) related to the manifestation of the issue
- The location of the affected source code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce the issue
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit it

## Preferred Languages

We prefer all communications to be in English.

## Security Best Practices

When deploying this application:

1. **Never commit `.env` files** - Use environment variables or secret management
2. **Use strong secrets** - Generate with `openssl rand -hex 32`
3. **Enable HTTPS** - Always use SSL/TLS in production
4. **Keep dependencies updated** - Regularly run `uv sync` or `pip install --upgrade`
5. **Monitor logs** - Check for suspicious activity
6. **Rate limiting** - Already configured, adjust as needed
7. **Database backups** - Implement regular backup strategy
