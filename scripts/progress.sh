# SPDX-License-Identifier: GPL-3.0-or-later
# Shared progress-bar helpers for build.sh / install.sh. Source, don't execute.
#
#   progress_start "title"        begin a bar (records the start time)
#   progress_tail FILE            live-tail FILE's last lines beneath the bar
#   progress_update PCT "label"   redraw at PCT % with a step label
#   progress_tick                 redraw unchanged (keeps elapsed ticking)
#   progress_done                 finish at 100% and newline
#   progress_fail                 mark failed and newline
#
# When stdout is not a TTY the bar is skipped and each new step is printed
# as a plain line instead; the tail is TTY-only.

_PROGRESS_TITLE=""
_PROGRESS_START=0
_PROGRESS_PCT=0
_PROGRESS_LABEL=""
_PROGRESS_TTY=0
_PROGRESS_WIDTH=20
_PROGRESS_TAIL_FILE=""
_PROGRESS_TAIL_LINES=3

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
    _progress_draw_tail
}

# Redraw the fixed tail window beneath the bar and return the cursor to the
# bar line. Lines are truncated to the terminal width so they never wrap —
# wrapping would break the cursor-up arithmetic.
_progress_draw_tail() {
    [[ -n "${_PROGRESS_TAIL_FILE}" ]] || return 0
    local cols width line i
    cols=$(tput cols 2>/dev/null || echo 80)
    width=$((cols - 5))
    ((width > 0)) || width=1
    local lines=()
    mapfile -t lines < <(tail -n "${_PROGRESS_TAIL_LINES}" "${_PROGRESS_TAIL_FILE}" 2>/dev/null \
        | tr -d '\r' | tr '\t' ' ')
    for ((i = 0; i < _PROGRESS_TAIL_LINES; i++)); do
        line="${lines[i]-}"
        printf '\n\033[K    \033[2m%s\033[0m' "${line:0:width}"
    done
    printf '\033[%dA\r' "${_PROGRESS_TAIL_LINES}"
}

# Erase the tail window (and the bar line, which the caller redraws) and stop
# tailing, so finished output is just the bar.
_progress_tail_clear() {
    [[ -n "${_PROGRESS_TAIL_FILE}" ]] || return 0
    _PROGRESS_TAIL_FILE=""
    printf '\r\033[0J'
}

progress_start() {
    _PROGRESS_TITLE="$1"
    _PROGRESS_START=$(date +%s)
    _PROGRESS_PCT=0
    _PROGRESS_LABEL=""
    _PROGRESS_TAIL_FILE=""
    if [[ -t 1 ]]; then
        _PROGRESS_TTY=1
        _progress_draw
    else
        _PROGRESS_TTY=0
        echo "${_PROGRESS_TITLE}:"
    fi
}

# progress_tail FILE — show a rolling tail of FILE's last lines beneath the
# bar, redrawn with the bar. TTY-only; a no-op line-wise when not a TTY.
progress_tail() {
    if [[ "${_PROGRESS_TTY}" -eq 1 ]]; then
        _PROGRESS_TAIL_FILE="$1"
        _progress_draw
    fi
    return 0
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
        _progress_tail_clear
        _progress_draw
        printf '\n'
    else
        printf '  100%%  done (%s)\n' "$(_progress_elapsed)"
    fi
}

progress_fail() {
    _PROGRESS_LABEL="FAILED"
    if [[ "${_PROGRESS_TTY}" -eq 1 ]]; then
        _progress_tail_clear
        _progress_draw
        printf '\n'
    else
        printf '  FAILED after %s\n' "$(_progress_elapsed)"
    fi
}
