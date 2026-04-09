#!/usr/bin/env bash
set -euo pipefail

# Install Python project in editable mode with dev extras
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

# Install Lean 4 via elan
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf \
  | sh -s -- -y --default-toolchain stable
echo 'export PATH="$HOME/.elan/bin:$PATH"' >> "$HOME/.bashrc"
export PATH="$HOME/.elan/bin:$PATH"

# Verify
python -m pytest --version
ruff --version
lean --version
