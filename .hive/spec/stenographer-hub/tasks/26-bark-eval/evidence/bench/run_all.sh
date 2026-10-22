#!/bin/bash
set -u
cd /tmp/claude-1000/-home-penguin-source-hive-projects-stenographer-worktrees-26-bark-eval/b0fa8503-4f88-4497-8ce3-370a022bb116/scratchpad
R=/home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.scratch/results; mkdir -p $R
SV=/home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.scratch/venv/bin/python; MV=/home/penguin/source/stenographer/.venv/bin/python
step() { echo "=== $1 $(date +%T) load: $(cut -d' ' -f1-3 /proc/loadavg)"; shift; "$@" 2>&1 | grep -vE "Warning|warn|Loading weights|_VF.lstm"; }
step turbo-cuda $MV -I /home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_whisper.py cuda /home/penguin/.cache/huggingface/hub/models--dropbox-dash--faster-whisper-large-v3-turbo/snapshots/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf/ $R/turbo-ct2-cuda.json
step turbo-cpu  $MV -I /home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_whisper.py cpu /home/penguin/.cache/huggingface/hub/models--dropbox-dash--faster-whisper-large-v3-turbo/snapshots/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf/ $R/turbo-ct2-cpu.json
step pro-cuda   $SV -I /home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_hf.py pro cuda $R/pro-hf-cuda.json
step clean-cuda $SV -I /home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_hf.py clean cuda $R/clean-hf-cuda.json
step pro-sherpa $MV -I /home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_sherpa.py pro-sherpa-int8-cpu /home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.scratch/models/bark-pro-sherpa 0.25 $R/pro-sherpa-int8-cpu.json
step clean-sherpa $MV -I /home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_sherpa.py clean-sherpa-int8-cpu /home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.scratch/vet-velddev-clean 0.0 $R/clean-sherpa-int8-cpu.json
step pro-cpu    $SV -I /home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_hf.py pro cpu $R/pro-hf-cpu.json
step clean-cpu  $SV -I /home/penguin/source/hive/projects/stenographer/worktrees/26-bark-eval/.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_hf.py clean cpu $R/clean-hf-cpu.json
echo ALLDONE
