# SPDX-License-Identifier: GPL-3.0-or-later
"""Writing defaults: rendering `Config.defaults()` back out as the annotated
default TOML document (`write_default`)."""

from __future__ import annotations

from stenographer.config.schema import CUE_NAMES


def _format_default_toml() -> str:
    # Deferred import to break the config package's initialisation cycle:
    # __init__ imports this module while defining Config. Safe at call time --
    # the package is fully initialised before anyone renders the default TOML.
    from stenographer.config import Config

    cfg = Config.defaults()
    h = cfg.hotkey
    a = cfg.audio
    r = cfg.asr
    f = cfg.feedback
    v = cfg.visualizer
    o = cfg.output
    c = cfg.clipboard
    i = cfg.incremental
    fm = cfg.formatting
    u = cfg.update
    lines: list[str] = [
        "# stenographer configuration",
        "",
        "[stenographer]",
        "",
        "# Hotkey",
        f"hotkey.binding = {_toml_str(h.binding)}",
        f"hotkey.toggle_threshold_seconds = {h.toggle_threshold_seconds}",
        f"hotkey.double_tap_window_seconds = {h.double_tap_window_seconds}",
        f"hotkey.cancel_binding = {_toml_str(h.cancel_binding)}",
        f"hotkey.device = {_toml_optional(h.device)}",
        f"hotkey.trigger_mode = {_toml_str(h.trigger_mode)}",
        "",
        "# Audio capture",
        f"audio.sample_rate = {a.sample_rate}",
        f"audio.frames_per_buffer = {a.frames_per_buffer}",
        f"audio.input_device = {_toml_optional(a.input_device)}",
        f"audio.max_recording_seconds = {a.max_recording_seconds}",
        "# 0 disables the pre-decode energy gate",
        f"audio.min_speech_rms = {a.min_speech_rms}",
        "",
        "# ASR",
        f"asr.model = {_toml_str(r.model)}",
        f"asr.language = {_toml_str(r.language)}",
        f"asr.beam_size = {r.beam_size}",
        f"asr.compute_type = {_toml_str(r.compute_type)}",
        f"asr.silence_threshold = {r.silence_threshold}",
        f"asr.vad_filter = {_toml_bool(r.vad_filter)}",
        f"asr.max_new_tokens = {r.max_new_tokens}",
        "# 0 detects affinity-available physical cores (maximum 8)",
        f"asr.cpu_threads = {r.cpu_threads}",
        f"asr.mode = {_toml_str(r.mode)}",
        f"asr.idle_unload_seconds = {r.idle_unload_seconds}",
        '# hotwords: proper nouns / jargon to bias recognition toward, e.g. "wtype, Wayland"',
        f"asr.hotwords = {_toml_optional(r.hotwords)}",
        "# initial_prompt: free-text context prepended to decoding (style/domain hints)",
        f"asr.initial_prompt = {_toml_optional(r.initial_prompt)}",
        "",
        "# Audio feedback",
        f"feedback.volume = {f.volume}",
        f"feedback.mute = {_toml_bool(f.mute)}",
        "",
        "# Bottom-center Wayland spectrum overlay",
        f"visualizer.enabled = {_toml_bool(v.enabled)}",
        f"visualizer.frequency_bands = {v.frequency_bands}",
        f"visualizer.min_frequency = {v.min_frequency}",
        f"visualizer.max_frequency = {v.max_frequency}",
        f"visualizer.margin_bottom = {v.margin_bottom}",
        "",
        "# Text output",
        f"output.injection_method = {_toml_str(o.injection_method)}",
        f"output.append_trailing_space = {_toml_bool(o.append_trailing_space)}",
        f"output.max_chars = {o.max_chars}",
        "",
        "# Clipboard",
        f"clipboard.enabled = {_toml_bool(c.enabled)}",
        "",
        "# Incremental word-level decoding (always enabled).",
        "# min_chunk_seconds / beam_size are the CPU knobs if re-decodes lag.",
        f"incremental.min_chunk_seconds = {i.min_chunk_seconds}",
        f"incremental.agreement_n = {i.agreement_n}",
        "incremental.beam_size = null"
        if i.beam_size is None
        else f"incremental.beam_size = {i.beam_size}",
        f"incremental.max_buffer_seconds = {i.max_buffer_seconds}",
        f"incremental.interim_timeout_seconds = {i.interim_timeout_seconds}",
        f"incremental.release_timeout_seconds = {i.release_timeout_seconds}",
        "",
        "# Formatting heuristics (applies to all output modes)",
        f"formatting.paragraph_pause_seconds = {fm.paragraph_pause_seconds}",
        f"formatting.capitalize_sentences = {_toml_bool(fm.capitalize_sentences)}",
        f"formatting.normalize_spacing = {_toml_bool(fm.normalize_spacing)}",
        "",
        "# Update",
        f"update.check_on_startup = {_toml_bool(u.check_on_startup)}",
        f"update.repo = {_toml_str(u.repo)}",
        f"update.channel = {_toml_str(u.channel)}",
        f"update.base_url = {_toml_str(u.base_url)}",
        f"update.asset_pattern = {_toml_str(u.asset_pattern)}",
        f"update.timeout_seconds = {u.timeout_seconds}",
        "",
        "[stenographer.feedback.cues]",
    ]
    for name in CUE_NAMES:
        lines.append(f"{name} = {_toml_optional(f.cues[name])}")
    lines.append("")
    return "\n".join(lines)


def _toml_str(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_optional(v: str | None) -> str:
    if v is None:
        return '""'
    return _toml_str(v)


def _toml_bool(b: bool) -> str:
    return "true" if b else "false"
