# Install from Zero — Frood

Install Frood from zero on a clean machine or container.

## Prerequisites

- Python 3.11+
- `git`
- `docker` (optional, for container install)

## Procedure

1. **Clone the repo**

   ```bash
   git clone https://github.com/SalesTeamToolbox/frood.git
   cd frood
   ```

2. **Create and activate a virtual environment**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   make install-dev
   ```

4. **Verify**

   ```bash
   make lint
   make test
   make check
   ```

5. **Optional: build and run the container**

   ```bash
   docker build -t frood .
   docker run -p 8000:8000 frood
   ```

## Notes

- `make lint` may report pre-existing ruff errors in the base tree (see M8 release-gates report).
- `make test` runs the full pytest suite.
- Frood has no public deploy target — deploy truth is a stated gap (see M8 release-gates report).
