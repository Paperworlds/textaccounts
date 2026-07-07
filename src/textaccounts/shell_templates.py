"""Shell integration templates and completion snippets.

All string constants here are written verbatim to files by `textaccounts install`.
Keep them self-contained — no Python string interpolation at install time.
"""

_FISH_FUNCTION = """\
# textaccounts — shell integration
# Wraps the Python CLI so that `textaccounts switch` sets CLAUDE_CONFIG_DIR
# and CLAUDE_PROFILE in the current shell. All other subcommands pass through.
# Installed by: textaccounts install

function textaccounts --description "Manage Claude Code profiles"
    if test (count $argv) -ge 1; and test "$argv[1]" = "switch"
        eval (command textaccounts show --shell fish $argv[2..-1])
    else
        command textaccounts $argv
    end
end
"""

# Completions for the `switch` pseudo-command (provided by the shell wrapper
# function, not by Click). Appended after the Click-generated body so users
# get tab-completion for `textaccounts switch <profile>` and `ta switch ...`.
_FISH_SWITCH_COMPLETIONS = """\

# --- `switch` is a shell function (not a Click command) — add it manually ---
function __textaccounts_profiles
    command textaccounts repos | awk '{print $2}'
end
complete -c textaccounts -f -n "__fish_use_subcommand" -a "switch" -d "Switch the current shell to a profile"
# Suppress Click's top-level command suggestions once `switch` has been typed.
complete -c textaccounts -f -n "__fish_seen_subcommand_from switch" -a "(__textaccounts_profiles) default" -d "Profile"
complete -c ta --wraps textaccounts
"""

_FISH_TA_FUNCTION = """\
# ta — shorthand for textaccounts (with switch support)
# Installed by: textaccounts install

function ta --wraps=textaccounts --description 'textaccounts shortcut'
    textaccounts $argv
end
"""

# Click 8.3.2's fish source wrapper expects comma-separated "type,name\tdesc"
# but the runtime now emits newline-separated triplets (type, value, desc).
# Upstream bug — until fixed, we ship a corrected wrapper that consumes
# the actual runtime format.
_FISH_CLICK_WRAPPER = """\
function _textaccounts_completion
    set -l response (env _TEXTACCOUNTS_COMPLETE=fish_complete \\
        COMP_WORDS=(commandline -cp) COMP_CWORD=(commandline -t) textaccounts 2>/dev/null)
    set -l n (count $response)
    set -l i 1
    while test $i -le $n
        set -l ctype $response[$i]
        set -l value ""
        set -l desc ""
        if test (math $i + 1) -le $n
            set value $response[(math $i + 1)]
        end
        if test (math $i + 2) -le $n
            set desc $response[(math $i + 2)]
        end
        if test "$ctype" = "dir"
            __fish_complete_directories "$value"
        else if test "$ctype" = "file"
            __fish_complete_path "$value"
        else if test "$ctype" = "plain"
            if test -n "$desc"
                printf "%s\\t%s\\n" "$value" "$desc"
            else
                echo $value
            end
        end
        set i (math $i + 3)
    end
end
# Suppress Click's completion when `switch` is the subcommand (Click does
# not know about `switch` — handled by the shell wrapper). The manual rule
# in _FISH_SWITCH_COMPLETIONS takes over there.
complete --no-files --command textaccounts -n "not __fish_seen_subcommand_from switch" --arguments "(_textaccounts_completion)"
"""

# -- Bash / Zsh templates ---------------------------------------------------

_BASH_FUNCTION = """\
# textaccounts — shell integration
# Wraps the Python CLI so that `textaccounts switch` sets CLAUDE_CONFIG_DIR
# in the current shell. All other subcommands pass through.
# Installed by: textaccounts install
# Source this from ~/.bashrc

textaccounts() {
    if [ "$1" = "switch" ]; then
        eval "$(command textaccounts show --shell bash "${@:2}")"
    else
        command textaccounts "$@"
    fi
}

ta() { textaccounts "$@"; }
"""

# Bash supplement for the `switch` pseudo-command. Click's bash completion
# uses _TEXTACCOUNTS_COMPLETE under the hood; the wrapper intercepts switch
# before Click sees it, so we widen the command list here.
_BASH_SWITCH_COMPLETIONS = """\

# --- `switch` is a shell function — add it to completion ---
_textaccounts_switch_complete() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    if [ "${COMP_WORDS[1]}" = "switch" ] && [ "$COMP_CWORD" -ge 2 ]; then
        local profiles
        profiles="$(command textaccounts repos | awk '{print $2}') default"
        COMPREPLY=( $(compgen -W "$profiles" -- "$cur") )
    fi
}
complete -F _textaccounts_switch_complete -o default textaccounts
complete -F _textaccounts_switch_complete -o default ta
"""

_ZSH_FUNCTION = """\
# textaccounts — shell integration
# Wraps the Python CLI so that `textaccounts switch` sets CLAUDE_CONFIG_DIR
# in the current shell. All other subcommands pass through.
# Installed by: textaccounts install
# Source this from ~/.zshrc

textaccounts() {
    if [[ "$1" == "switch" ]]; then
        eval "$(command textaccounts show --shell zsh "${@:2}")"
    else
        command textaccounts "$@"
    fi
}

ta() { textaccounts "$@"; }
"""

# Zsh supplement for the `switch` pseudo-command. Sourced after Click's
# generated zsh completion to add profile-name completion for `switch`.
_ZSH_SWITCH_COMPLETIONS = """\

# --- `switch` is a shell function — add it to completion ---
_textaccounts_switch_profiles() {
    local -a profiles
    profiles=(${(f)"$(command textaccounts repos | awk '{print $2}')"})
    profiles+=(default)
    _describe 'profile' profiles
}
compdef '_arguments "1:command:(switch)" "*::profile:_textaccounts_switch_profiles"' ta-switch-helper
"""
