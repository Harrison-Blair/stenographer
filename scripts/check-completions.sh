#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Validate native completion syntax and representative results with real shells.
set -euo pipefail

cd "$(dirname "$0")/.."

CLI="${STENOGRAPHER_CLI:-.venv/bin/stenographer}"
for executable in "${CLI}" bash zsh fish; do
    command -v "${executable}" >/dev/null || {
        echo "error: required executable not found: ${executable}" >&2
        exit 1
    }
done

completion_tmp=$(mktemp -d)
trap 'rm -rf -- "${completion_tmp}"' EXIT
mkdir -p "${completion_tmp}/files"
touch "${completion_tmp}/files/sample.wav"

"${CLI}" completion bash > "${completion_tmp}/stenographer.bash"
"${CLI}" completion zsh > "${completion_tmp}/_stenographer"
"${CLI}" completion fish > "${completion_tmp}/stenographer.fish"

bash -n "${completion_tmp}/stenographer.bash"
zsh -n "${completion_tmp}/_stenographer"
fish --no-execute "${completion_tmp}/stenographer.fish"

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
assert_completion fish stenographer completion f
cd "$2"
assert_completion sample.wav stenographer transcribe sam
BASH

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
assert_fish_completion fish 'stenographer completion f'
assert_fish_completion sample.wav 'stenographer transcribe sam'

echo "completion checks passed"
