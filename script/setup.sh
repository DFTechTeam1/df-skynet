#!/bin/bash

echo "Checking for uv..."

export PATH="$HOME/.local/bin:$PATH"

if command -v uv &> /dev/null; then
  echo "uv is already installed: $(uv --version)"
else
  echo "uv not found, installing..."
  curl -Ls https://astral.sh/uv/install.sh | sh

  grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

  echo "uv installed: $(uv --version)"
fi

echo "Syncing dependencies with uv..."
uv sync

echo "Setup complete."
