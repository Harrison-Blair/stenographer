# SPDX-License-Identifier: GPL-3.0-or-later

function __stenographer_needs_command
    set -l tokens (commandline -opc)
    test (count $tokens) -eq 1
end

function __stenographer_command_is
    set -l tokens (commandline -opc)
    test (count $tokens) -ge 2; and test "$tokens[2]" = "$argv[1]"
end

function __stenographer_nested_command_needed
    set -l tokens (commandline -opc)
    test (count $tokens) -eq 2; and test "$tokens[2]" = "$argv[1]"
end

function __stenographer_transcribe_file_needed
    set -l tokens (commandline -opc)
    test (count $tokens) -ge 2; or return 1
    test "$tokens[2]" = transcribe; or return 1
    for token in $tokens[3..-1]
        string match -q -- '-*' "$token"; or return 1
    end
    return 0
end

complete -c stenographer -n __stenographer_needs_command -f -a run \
    -d 'Run the dictation daemon'
complete -c stenographer -n __stenographer_needs_command -f -a transcribe \
    -d 'Transcribe an audio file'
complete -c stenographer -n __stenographer_needs_command -f -a model \
    -d 'Manage the ASR model'
complete -c stenographer -n __stenographer_needs_command -f -a doctor \
    -d 'Probe required capabilities'
complete -c stenographer -n __stenographer_needs_command -f -a devices \
    -d 'List audio input devices'
complete -c stenographer -n __stenographer_needs_command -f -a setup \
    -d 'Interactively configure stenographer'
complete -c stenographer -n __stenographer_needs_command -f -a sounds \
    -d 'List, preview, or select a sound pack'
complete -c stenographer -n __stenographer_needs_command -f -a completion \
    -d 'Emit a native shell completion definition'
complete -c stenographer -n __stenographer_needs_command -f -s h -l help \
    -d 'Show help'
complete -c stenographer -n __stenographer_needs_command -f -l version \
    -d 'Show version'

for command in run transcribe model doctor devices setup sounds completion
    complete -c stenographer -n "__stenographer_command_is $command" -f -s h -l help \
        -d 'Show help'
end

complete -c stenographer -n '__stenographer_command_is transcribe' -f -l raw \
    -d 'Emit the unformatted transcript'
complete -c stenographer -n __stenographer_transcribe_file_needed -F
complete -c stenographer -n '__stenographer_command_is setup' -f -l quick \
    -d 'Configure essentials only'
complete -c stenographer -n '__stenographer_command_is setup' -f -l default \
    -d 'Write the annotated default configuration'

complete -c stenographer -n '__stenographer_command_is sounds' -f -l list \
    -d 'List available sound packs'
complete -c stenographer -n '__stenographer_command_is sounds' -f -l preview \
    -d 'Preview a sound pack without selecting it'
complete -c stenographer -n '__stenographer_command_is sounds' -f \
    -a 'legacy warm-desk soft-electronic minimal-ui'

complete -c stenographer -n '__stenographer_nested_command_needed model' -f -a download \
    -d 'Download the ASR model'

complete -c stenographer -n '__stenographer_nested_command_needed completion' -f \
    -a 'bash zsh fish'
