#!/bin/bash

set -e

echo "Checking for uv..."

export PATH="$HOME/.local/bin:$PATH"

if command -v uv >/dev/null 2>&1; then
  echo "uv is already installed: $(uv --version)"
else
  echo "uv not found, installing..."
  curl -Ls https://astral.sh/uv/install.sh | sh

  grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

  echo "uv installed: $(uv --version)"
fi

echo "Syncing dependencies with uv..."
uv sync

echo "Installing git hooks..."
uv run pre-commit install

echo "Setup complete."
