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
cat > "${completion_tmp}/cases" <<'CASES'
run|stenographer 
download|stenographer model 
--raw|stenographer transcribe --
sounds|stenographer s
minimal-ui|stenographer sounds m
--preview|stenographer sounds --p
fish|stenographer completion f
sample.wav|stenographer transcribe sam
CASES

if command -v bash >/dev/null; then
    "${CLI}" completion bash > "${completion_tmp}/stenographer.bash"
    bash -n "${completion_tmp}/stenographer.bash"

    bash -s -- "${completion_tmp}/stenographer.bash" "${completion_tmp}/files" "${completion_tmp}/cases" <<'BASH'
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

cd "$2"
while IFS='|' read -r expected input; do
    read -r -a words <<< "${input}"
    [[ "${input}" == *' ' ]] && words+=("")
    assert_completion "${expected}" "${words[@]}"
done < "$3"
BASH
    checked_shells+=(bash)
else
    echo "completion check skipped: bash is not available" >&2
fi

if command -v zsh >/dev/null; then
    "${CLI}" completion zsh > "${completion_tmp}/_stenographer"
    zsh -n "${completion_tmp}/_stenographer"

    zsh -s -- "${completion_tmp}/_stenographer" "${completion_tmp}/files" "${completion_tmp}/cases" <<'ZSH'
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

cd "$2"
while IFS='|' read -r expected input; do
    input_words=(${=input})
    [[ "${input}" == *' ' ]] && input_words+=('')
    capture "${input_words[@]}"
    assert_candidate "${expected}"
done < "$3"
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

    while IFS='|' read -r expected input; do
        assert_fish_completion "${expected}" "${input}"
    done < "${completion_tmp}/cases"
    checked_shells+=(fish)
else
    echo "completion check skipped: fish is not available" >&2
fi

if ((${#checked_shells[@]} == 0)); then
    echo "error: no supported shell is available for completion checks" >&2
    exit 1
fi

echo "completion checks passed: ${checked_shells[*]}"
