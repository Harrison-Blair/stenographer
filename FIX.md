# FIX.md: switch this machine to Bark Pro

This file is temporary. A later commit deletes it after every machine is
done. Paste the prompt below into a coding agent on each machine after you
update the stenographer checkout to this `dev`.

---

You are helping me move this machine's stenographer from Whisper to
Underdog Bark 3.0 Pro. Do these steps in order. Stop and tell me when a step
fails.

1. **Prerequisite.** Never run `sudo` yourself. Ask me to run
   `sudo apt install python3-venv`. Then check it with
   `python3 -c 'import ensurepip'`. It must exit without an error.
2. **Update the app.** In the stenographer checkout, run
   `scripts/reinstall.sh --no-start`. It stops a running service and
   rebuilds the bundle. The checkout must be on the updated `dev`.
3. **Build the speech model.** Run `stenographer model download --asr`. It
   needs 10 GiB of free disk and about 10.2 GiB of RAM while it converts.
   Check both first (`df -h ~/.local/share`, `free -h`) and tell me if either
   is short. It took about 2 minutes on a 16-core machine.
4. **Check.** Run `stenographer doctor` and show me any warning or failure.
5. **Old config keys.** Open `~/.config/stenographer/config.toml`. Under
   `[stenographer.asr]`, show me any of these keys: `model`, `compute_type`,
   `beam_size`, `hotwords`, `initial_prompt`, `vad_filter`,
   `silence_threshold`. Stenographer now ignores them, so they are harmless.
   Remove them only if I agree, with a normal edit of that file. Keep
   `idle_unload_seconds` and `cpu_threads`.
6. **Old Whisper model cache.** Look for
   `~/.cache/huggingface/hub/models--deepdml--faster-whisper-large-v3-turbo-ct2`.
   If it exists, show me its size (`du -sh`). Delete it only if I agree.
   Do not touch any other folder in that cache.
7. **Microphone.** Never open the microphone, and never start
   `stenographer run`, `stenographer live` or a dictation test, unless I
   say yes first.
8. **Start.** Ask me before you run
   `systemctl --user start stenographer.service`.

At the end, tell me what you did, what I declined, and what is left.
