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

# Install shell integration (fish) + aliases
install-shell:
    uv run textaccounts install --shell fish
    #!/usr/bin/env sh
    mkdir -p "$HOME/.config/fish/functions"
    for f in completions/functions/*.fish; do
        cp "$f" "$HOME/.config/fish/functions/$(basename $f)"
        echo "Installed fish function → $HOME/.config/fish/functions/$(basename $f)"
    done

# Launch the interactive view
view:
    uv run textaccounts view

# Show current version
version:
    @grep '^version' pyproject.toml | head -1
