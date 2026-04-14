default:
    @just --list

# Run tests
test:
    uv run pytest -x -q

# Install as editable uv tool (no venv required)
install:
    uv tool install -e . --force --python 3.13

# Build distribution
build:
    uv build

# Install shell integration (fish) + aliases
install-shell:
    uv run textaccounts install --shell fish
    mkdir -p "$HOME/.config/fish/functions"
    cp completions/functions/*.fish "$HOME/.config/fish/functions/"
    @echo "Installed fish alias functions"

# Launch the interactive view
view:
    uv run textaccounts view

# Show current version
version:
    @grep '^version' pyproject.toml | head -1
