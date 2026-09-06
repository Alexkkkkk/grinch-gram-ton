#!/bin/bash
# Install git hooks for local development
set -e

echo "Installing git hooks..."
cp .github/hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
echo "✅ Hooks installed. Pre-commit checks will run on every commit."
