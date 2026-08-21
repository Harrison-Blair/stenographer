# SPDX-License-Identifier: GPL-3.0-or-later

_stenographer() {
    local cur command index has_file
    cur="${COMP_WORDS[COMP_CWORD]}"
    command="${COMP_WORDS[1]-}"
    COMPREPLY=()

    if ((COMP_CWORD == 1)); then
        mapfile -t COMPREPLY < <(
            compgen -W 'run transcribe model doctor devices setup completion -h --help --version' -- "${cur}"
        )
        return
    fi

    case "${command}" in
        run|doctor|devices)
            mapfile -t COMPREPLY < <(compgen -W '-h --help' -- "${cur}")
            ;;
        setup)
            mapfile -t COMPREPLY < <(compgen -W '-h --help --quick' -- "${cur}")
            ;;
        model)
            if ((COMP_CWORD == 2)); then
                mapfile -t COMPREPLY < <(compgen -W 'download -h --help' -- "${cur}")
            elif [[ "${COMP_WORDS[2]-}" == download ]]; then
                mapfile -t COMPREPLY < <(compgen -W '-h --help' -- "${cur}")
            fi
            ;;
        completion)
            if ((COMP_CWORD == 2)); then
                mapfile -t COMPREPLY < <(compgen -W 'bash zsh fish -h --help' -- "${cur}")
            else
                mapfile -t COMPREPLY < <(compgen -W '-h --help' -- "${cur}")
            fi
            ;;
        transcribe)
            if [[ "${cur}" == -* ]]; then
                mapfile -t COMPREPLY < <(compgen -W '-h --help --raw' -- "${cur}")
                return
            fi
            has_file=0
            for ((index = 2; index < COMP_CWORD; index++)); do
                if [[ "${COMP_WORDS[index]}" != -* ]]; then
                    has_file=1
                    break
                fi
            done
            if ((has_file)); then
                mapfile -t COMPREPLY < <(compgen -W '-h --help --raw' -- "${cur}")
            else
                mapfile -t COMPREPLY < <(compgen -f -- "${cur}")
                compopt -o filenames 2>/dev/null || true
            fi
            ;;
    esac
}

complete -F _stenographer stenographer
