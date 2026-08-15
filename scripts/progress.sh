# SPDX-License-Identifier: GPL-3.0-or-later
# Shared progress-bar helpers for build.sh / install.sh. Source, don't execute.
#
#   progress_start "title"        begin a bar (records the start time)
#   progress_update PCT "label"   redraw at PCT % with a step label
#   progress_tick                 redraw unchanged (keeps elapsed ticking)
#   progress_done                 finish at 100% and newline
#   progress_fail                 mark failed and newline
#
# When stdout is not a TTY the bar is skipped and each new step is printed
# as a plain line instead.

_PROGRESS_TITLE=""
_PROGRESS_START=0
_PROGRESS_PCT=0
_PROGRESS_LABEL=""
_PROGRESS_TTY=0
_PROGRESS_WIDTH=20

_progress_elapsed() {
    local secs=$(($(date +%s) - _PROGRESS_START))
    printf '%d:%02d' $((secs / 60)) $((secs % 60))
}

_progress_draw() {
    local filled=$((_PROGRESS_PCT * _PROGRESS_WIDTH / 100))
    local bar=""
    local i
    for ((i = 0; i < _PROGRESS_WIDTH; i++)); do
        if ((i < filled)); then bar+="█"; else bar+="░"; fi
    done
    printf '\r\033[K  %-10s [%s] %3d%%  %-24s %s' \
        "${_PROGRESS_TITLE}" "${bar}" "${_PROGRESS_PCT}" "${_PROGRESS_LABEL}" \
        "$(_progress_elapsed)"
}

progress_start() {
    _PROGRESS_TITLE="$1"
    _PROGRESS_START=$(date +%s)
    _PROGRESS_PCT=0
    _PROGRESS_LABEL=""
    if [[ -t 1 ]]; then
        _PROGRESS_TTY=1
        _progress_draw
    else
        _PROGRESS_TTY=0
        echo "${_PROGRESS_TITLE}:"
    fi
}

progress_update() {
    _PROGRESS_PCT="$1"
    if [[ "${2-}" != "${_PROGRESS_LABEL}" ]]; then
        _PROGRESS_LABEL="${2-}"
        if [[ "${_PROGRESS_TTY}" -eq 0 && -n "${_PROGRESS_LABEL}" ]]; then
            printf '  %3d%%  %s\n' "${_PROGRESS_PCT}" "${_PROGRESS_LABEL}"
        fi
    fi
    [[ "${_PROGRESS_TTY}" -eq 1 ]] && _progress_draw
    return 0
}

progress_tick() {
    [[ "${_PROGRESS_TTY}" -eq 1 ]] && _progress_draw
    return 0
}

progress_done() {
    _PROGRESS_PCT=100
    _PROGRESS_LABEL="done"
    if [[ "${_PROGRESS_TTY}" -eq 1 ]]; then
        _progress_draw
        printf '\n'
    else
        printf '  100%%  done (%s)\n' "$(_progress_elapsed)"
    fi
}

progress_fail() {
    _PROGRESS_LABEL="FAILED"
    if [[ "${_PROGRESS_TTY}" -eq 1 ]]; then
        _progress_draw
        printf '\n'
    else
        printf '  FAILED after %s\n' "$(_progress_elapsed)"
    fi
}
