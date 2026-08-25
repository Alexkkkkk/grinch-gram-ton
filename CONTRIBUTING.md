# Contributing to GRINCH-GRAM

## Development Setup

```bash
git clone https://github.com/Alexkkkkk/grinch-gram-ton.git
cd grinch-gram-ton
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pre-commit
pre-commit install
```

## Code Style

- **Black** for formatting
- **Ruff** for linting
- **MyPy** for type checking

Run before commit:
```bash
make fmt
make lint
make test
```

## Branch Naming

- `feature/description` — new features
- `fix/description` — bug fixes
- `refactor/description` — code refactoring
- `docs/description` — documentation

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new trading strategy
fix: correct stop-loss calculation
docs: update API documentation
refactor: split trader into modules
test: add unit tests for grid engine
```
