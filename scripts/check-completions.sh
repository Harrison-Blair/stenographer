#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Validate syntax and representative results for every native shell available locally.
set -euo pipefail

cd "$(dirname "$0")/.."

CLI="${STENOGRAPHER_CLI:-.venv/bin/stenographer}"
if [[ ! -x "${CLI}" ]] && ! command -v "${CLI}" >/dev/null; then
    echo "error: required executable not found: ${CLI}" >&2
    exit 1
fi

completion_tmp=$(mktemp -d)
trap 'rm -rf -- "${completion_tmp}"' EXIT
mkdir -p "${completion_tmp}/files"
touch "${completion_tmp}/files/sample.wav"
checked_shells=()

if command -v bash >/dev/null; then
    "${CLI}" completion bash > "${completion_tmp}/stenographer.bash"
    bash -n "${completion_tmp}/stenographer.bash"

    bash -s -- "${completion_tmp}/stenographer.bash" "${completion_tmp}/files" <<'BASH'
set -euo pipefail
source "$1"
complete -p stenographer >/dev/null

assert_completion() {
    local expected=$1
    shift
    COMP_WORDS=("$@")
    COMP_CWORD=$((${#COMP_WORDS[@]} - 1))
    COMPREPLY=()
    _stenographer
    local candidate
    for candidate in "${COMPREPLY[@]}"; do
        [[ "${candidate}" == "${expected}" ]] && return
    done
    echo "bash completion missing ${expected} for: $*" >&2
    exit 1
}

assert_completion run stenographer ""
assert_completion download stenographer model ""
assert_completion --raw stenographer transcribe --
assert_completion sounds stenographer s
assert_completion minimal-ui stenographer sounds m
assert_completion --preview stenographer sounds --p
assert_completion fish stenographer completion f
cd "$2"
assert_completion sample.wav stenographer transcribe sam
BASH
    checked_shells+=(bash)
else
    echo "completion check skipped: bash is not available" >&2
fi

if command -v zsh >/dev/null; then
    "${CLI}" completion zsh > "${completion_tmp}/_stenographer"
    zsh -n "${completion_tmp}/_stenographer"

    zsh -s -- "${completion_tmp}/_stenographer" "${completion_tmp}/files" <<'ZSH'
set -euo pipefail
typeset registration=''
typeset -a candidates
compdef() { registration="$1:$2" }
source "$1"
[[ "${registration}" == '_stenographer:stenographer' ]]

_values() { candidates=("${@:2}") }
_files() { candidates=("${PREFIX}"*(N:t)) }

capture() {
    words=("$@")
    CURRENT=$#
    PREFIX="${words[CURRENT]}"
    candidates=()
    _stenographer
}

assert_candidate() {
    local expected=$1 candidate
    for candidate in "${candidates[@]}"; do
        [[ "${candidate}" == "${expected}" || "${candidate}" == "${expected}["* ]] && return
    done
    print -u2 "zsh completion missing ${expected}"
    exit 1
}

capture stenographer ''
assert_candidate run
capture stenographer model ''
assert_candidate download
capture stenographer transcribe --
assert_candidate --raw
capture stenographer s
assert_candidate sounds
capture stenographer sounds m
assert_candidate minimal-ui
capture stenographer sounds --p
assert_candidate --preview
capture stenographer completion f
assert_candidate fish
cd "$2"
capture stenographer transcribe sam
assert_candidate sample.wav
ZSH

    zsh -s -- "${completion_tmp}" <<'ZSH'
set -euo pipefail
fpath=("$1" $fpath)
autoload -Uz compinit
compinit -D -i
[[ "${_comps[stenographer]}" == _stenographer ]]

typeset -a candidates
_values() { candidates=("${@:2}") }
words=(stenographer '')
CURRENT=2
PREFIX=''
_stenographer
found=0
for candidate in "${candidates[@]}"; do
    [[ "${candidate}" == 'run['* ]] && found=1
done
((found))
ZSH
    checked_shells+=(zsh)
else
    echo "completion check skipped: zsh is not available" >&2
fi

if command -v fish >/dev/null; then
    "${CLI}" completion fish > "${completion_tmp}/stenographer.fish"
    fish --no-execute "${completion_tmp}/stenographer.fish"

    assert_fish_completion() {
        local expected=$1 input=$2 output
        output=$(cd "${completion_tmp}/files" && fish -c \
            'source $argv[1]; complete -C "$argv[2]"' \
            "${completion_tmp}/stenographer.fish" "${input}")
        while IFS=$'\t' read -r candidate _description; do
            [[ "${candidate}" == "${expected}" ]] && return
        done <<< "${output}"
        echo "fish completion missing ${expected} for: ${input}" >&2
        exit 1
    }

    assert_fish_completion run 'stenographer '
    assert_fish_completion download 'stenographer model '
    assert_fish_completion --raw 'stenographer transcribe --'
    assert_fish_completion sounds 'stenographer s'
    assert_fish_completion minimal-ui 'stenographer sounds m'
    assert_fish_completion --preview 'stenographer sounds --p'
    assert_fish_completion fish 'stenographer completion f'
    assert_fish_completion sample.wav 'stenographer transcribe sam'
    checked_shells+=(fish)
else
    echo "completion check skipped: fish is not available" >&2
fi

if ((${#checked_shells[@]} == 0)); then
    echo "error: no supported shell is available for completion checks" >&2
    exit 1
fi

echo "completion checks passed: ${checked_shells[*]}"
