default:
    @just --list

# Run tests
test:
    uv run pytest -x -q

# Install as editable uv tool (no venv required)
install:
    uv tool install -e . --force

# Build distribution
build:
    uv build

# Install shell integration (fish)
install-shell:
    uv run textaccounts install --shell fish

# Launch the interactive view
view:
    uv run textaccounts view

# Show current version
version:
    @grep '^version' pyproject.toml | head -1
