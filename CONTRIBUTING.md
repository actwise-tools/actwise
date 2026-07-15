# Contributing to ActWise

Thanks for your interest in ActWise — an **unofficial, community** toolkit for
working with NICE Actimize ActOne. Contributions are welcome under the terms below.

## Ground rules (read first)

ActWise interoperates with proprietary systems. To keep this project safe to
maintain in the open, **every contribution must be free of proprietary or sensitive
material**. Do **not** include, attach, paste, or reference in code, tests, issues,
pull requests, commit messages, or discussions:

- NICE Actimize proprietary content — documentation text, database schemas, API
  specifications, catalogs, product keys, or license files (`*.lic`).
- Customer, production, or personal data of any kind.
- Credentials, tokens, cookies, `.env` files, or private keys.
- Internal or hosted endpoint identifiers (private hostnames, tunnels, IPs).

Use synthetic, clearly fictional sample data in examples and tests. If you are
unsure whether something is safe to share, **leave it out and ask first**.

## How to contribute

1. **Open an issue** describing the bug or proposal before large changes, so we can
   agree on direction.
2. **Fork** the repository and create a feature branch.
3. Keep changes **focused and small** — one logical change per pull request.
4. Match the existing code style. Python code is formatted/linted with
   [ruff](https://docs.astral.sh/ruff/):

   ```bash
   pip install -e ".[dev]"
   ruff check .
   pytest -q
   ```

5. Add or update tests for behavior you change. Network-dependent tests are marked
   `network` and are deselected by default — do not make the default suite require
   live credentials.
6. Update the relevant docs (`components/wiki/…`) when you change user-facing
   behavior.
7. **Open a pull request** with a clear description and link the issue it closes.

## Commit & PR expectations

- Write clear, imperative commit messages.
- CI must pass (lint + tests).
- By submitting a contribution, you certify that you have the right to do so and
  that your contribution contains no proprietary or confidential material, and you
  agree that your contribution is licensed under the project's Apache-2.0 license.

## Code of Conduct

All participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Please do **not** file security issues publicly. See [SECURITY.md](SECURITY.md).
