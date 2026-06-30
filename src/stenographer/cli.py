# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point and subcommand dispatch."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import logging
import os
import pathlib
import signal
import sys
from collections.abc import Sequence

import soundfile

from stenographer import __version__
from stenographer.asr.model import Model
from stenographer.asr.worker import Worker
from stenographer.audio.capture import Recorder
from stenographer.audio.feedback import CueName, Feedback
from stenographer.capabilities import Capabilities
from stenographer.config import Config
from stenographer.errors import fatal
from stenographer.hotkey.binding import HotkeyBinding
from stenographer.hotkey.listener import HotkeyListener
from stenographer.hotkey.state_machine import HotkeyStateMachine
from stenographer.notification import DesktopNotification
from stenographer.output.clipboard import ClipboardManager
from stenographer.output.inject import Injector
from stenographer.session import Session

log = logging.getLogger(__name__)

_LOCK_PATH = (
    pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    / "stenographer.lock"
)


def _resolve_asset_root() -> pathlib.Path:
    """Return the directory holding the bundled sound cues.

    In a wheel / editable install, the assets live next to ``cli.py``
    at ``<package>/assets/sounds``. In a PyInstaller ``--onedir``
    binary, ``cli`` is launched as a top-level entry and its
    ``__file__`` is ``_internal/cli.py`` (not under the
    ``stenographer`` package), so the assets are reached via
    ``sys._MEIPASS / "stenographer" / "assets" / "sounds"``.
    """
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return pathlib.Path(sys._MEIPASS) / "stenographer" / "assets" / "sounds"
    return pathlib.Path(__file__).resolve().parent / "assets" / "sounds"


_ASSET_ROOT = _resolve_asset_root()


def _configure_logging() -> None:
    state_dir = (
        pathlib.Path(os.environ.get("XDG_STATE_HOME", pathlib.Path.home() / ".local/state"))
        / "stenographer"
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    log_file = state_dir / "stenographer.log"
    level_name = os.environ.get("STENOGRAPHER_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, mode="a"),
        ],
    )


def _build_feedback(cfg: Config, caps: Capabilities) -> Feedback:
    if caps.has_pw_play:
        player = "pw-play"
    elif caps.has_paplay:
        player = "paplay"
    else:
        player = None
    override_root: dict[CueName, pathlib.Path] = {}
    for cue_name, path_str in cfg.feedback.cues.items():
        if path_str:
            override_root[cue_name] = pathlib.Path(path_str)
    return Feedback(
        player=player,
        asset_root=_ASSET_ROOT,
        override_root=override_root,
        volume=cfg.feedback.volume,
        muted=cfg.feedback.mute,
    )


def _install_signal_handlers(session: Session) -> None:
    """Install SIGINT/SIGTERM handlers that drain and stop the session.

    Per ``spec/08-process-model.md`` lifecycle: SIGINT and SIGTERM
    trigger a clean drain (finish in-flight utterance, close
    components, release the lock) and exit 0.
    """

    def _handler(signum: int, frame: object) -> None:
        log.info("signal: received %s, stopping", signal.Signals(signum).name)
        session.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handler)


def _acquire_single_instance_lock() -> int:
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        print("stenographer: another instance is already running.", file=sys.stderr)
        return 1
    os.write(fd, f"{os.getpid()}\n".encode())
    return 0


def _release_single_instance_lock() -> None:
    with contextlib.suppress(OSError):
        _LOCK_PATH.unlink(missing_ok=True)


def _build_session(cfg: Config, caps: Capabilities, one_shot: bool) -> Session:
    log.info("loading ASR model: %s", cfg.asr.model)
    model = Model(cfg.asr)
    worker = Worker(model, timeout_seconds=(cfg.asr.beam_size and 300.0) or 300.0)
    worker.start()
    feedback = _build_feedback(cfg, caps)
    recorder = Recorder(
        sample_rate=cfg.audio.sample_rate,
        frames_per_buffer=cfg.audio.frames_per_buffer,
        device=cfg.audio.input_device,
        on_error=lambda exc: log.error("recorder: %s", exc),
    )
    injector = Injector(
        available=caps.has_wtype,
        append_trailing_space=cfg.output.append_trailing_space,
        max_chars=cfg.output.max_chars,
    )
    clipboard = ClipboardManager(available=caps.has_wl_copy)
    notification = DesktopNotification(available=caps.has_swaync)
    binding = HotkeyBinding.parse(cfg.hotkey.binding)
    sm = HotkeyStateMachine(threshold_seconds=cfg.hotkey.toggle_threshold_seconds)
    session = Session(
        cfg=cfg,
        capabilities=caps,
        listener=None,
        recorder=recorder,
        worker=worker,
        feedback=feedback,
        injector=injector,
        clipboard=clipboard,
        notification=notification,
        one_shot=one_shot,
    )
    listener = HotkeyListener(
        binding=binding,
        device_path=cfg.hotkey.device or None,
        state_machine=sm,
        on_start=session.on_recording_start,
        on_stop=session.on_recording_stop,
        on_toggle_off=session.on_toggle_off,
        feedback=feedback,
        lock=session._lock,
    )
    session._listener = listener
    return session


def cmd_run(cfg: Config) -> int:
    caps = Capabilities.probe(cfg)
    if not (caps.has_input_group and caps.has_mic and caps.has_asr_model):
        missing = []
        if not caps.has_input_group:
            missing.append("input-group")
        if not caps.has_mic:
            missing.append("mic")
        if not caps.has_asr_model:
            missing.append("asr-model")
        fatal(
            "missing required capabilities: " + ", ".join(missing) + ". See `stenographer doctor`."
        )
    rc = _acquire_single_instance_lock()
    if rc != 0:
        return rc
    session = _build_session(cfg, caps, one_shot=False)
    session._listener.start()
    _install_signal_handlers(session)
    log.info("session: daemon running (pid=%d)", os.getpid())
    try:
        session.run()
    finally:
        session.stop()
        _release_single_instance_lock()
    return 0


def cmd_dictate(cfg: Config) -> int:
    caps = Capabilities.probe(cfg)
    if not (caps.has_mic and caps.has_asr_model):
        fatal("missing required capabilities: mic and/or asr-model")
    session = _build_session(cfg, caps, one_shot=True)
    session._listener.start()
    _install_signal_handlers(session)
    log.info("session: dictate mode armed; press the hotkey once")
    try:
        session.run()
    finally:
        session.stop()
    return 0


def cmd_transcribe(cfg: Config, path: pathlib.Path) -> int:
    if not path.exists():
        print(f"stenographer: file not found: {path}", file=sys.stderr)
        return 2
    caps = Capabilities.probe(cfg)
    if not caps.has_asr_model:
        fatal("ASR model not found; run `stenographer model download`")
    try:
        samples, sr = soundfile.read(str(path), dtype="float32", always_2d=True)
    except Exception as exc:
        print(f"stenographer: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    if sr != cfg.audio.sample_rate:
        log.warning(
            "transcribe: file sample rate is %d, configured is %d (faster-whisper will resample)",
            sr,
            cfg.audio.sample_rate,
        )
    log.info("transcribe: loading model %s", cfg.asr.model)
    model = Model(cfg.asr)
    result = model.transcribe(samples, cfg.asr.language, cfg.asr.beam_size)
    text = result.text
    if cfg.output.append_trailing_space:
        text = text.rstrip() + " "
    sys.stdout.write(text)
    sys.stdout.write("\n")
    return 0


def cmd_model_download(cfg: Config) -> int:
    from huggingface_hub import snapshot_download

    log.info("model download: %s", cfg.asr.model)
    snapshot_download(
        repo_id=cfg.asr.model,
        allow_patterns=[
            "*.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.*",
            "preprocessor_config.json",
        ],
    )
    print(f"stenographer: downloaded {cfg.asr.model}")
    return 0


def cmd_doctor(cfg: Config, config_path: pathlib.Path) -> int:
    caps = Capabilities.probe(cfg)
    print("stenographer doctor")
    print("===================")
    print(f"config:         {config_path}")
    print(f"asr.model:      {cfg.asr.model}")
    print(f"hotkey:         {cfg.hotkey.binding}")
    print(f"wtype:          {'yes' if caps.has_wtype else 'NO  (cursor injection disabled)'}")
    print(f"wl-copy:        {'yes' if caps.has_wl_copy else 'NO  (clipboard disabled)'}")
    has_audio = caps.has_pw_play or caps.has_paplay
    audio_str = "yes" if has_audio else "NO  (audio feedback disabled)"
    print(f"pw-play/paplay: {audio_str}")
    print(f"input group:    {'yes' if caps.has_input_group else 'NO  (hotkey disabled)'}")
    print(f"mic device:     {'yes' if caps.has_mic else 'NO  (recording disabled)'}")
    print(f"asr model:      {'yes' if caps.has_asr_model else 'NO  (transcription disabled)'}")
    print(f"swaync:         {'yes' if caps.has_swaync else 'NO  (desktop notification)'}")
    fatal_cap = not (caps.has_input_group and caps.has_mic and caps.has_asr_model)
    return 78 if fatal_cap else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stenographer",
        description="Local, offline, Wayland push-to-talk / toggle dictation.",
    )
    parser.add_argument("--config", type=pathlib.Path, default=None)
    parser.add_argument("--version", action="version", version=f"stenographer {__version__}")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    sub.add_parser("run", help="Start the daemon (blocks).")

    transcribe = sub.add_parser("transcribe", help="Transcribe an audio file and print to stdout.")
    transcribe.add_argument("file", type=pathlib.Path)

    sub.add_parser("dictate", help="One-shot dictation.")

    model = sub.add_parser("model", help="Model management.")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("download", help="Download the configured ASR model.")

    sub.add_parser("doctor", help="Print capability probe and resolved config.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    import multiprocessing

    multiprocessing.freeze_support()
    _configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.config is not None:
        os.environ["STENOGRAPHER_CONFIG"] = str(args.config)
    from stenographer.config import load_or_default, resolve_config_path

    cfg = load_or_default()
    config_path = resolve_config_path()
    if args.subcommand == "run":
        return cmd_run(cfg)
    if args.subcommand == "transcribe":
        return cmd_transcribe(cfg, args.file)
    if args.subcommand == "dictate":
        return cmd_dictate(cfg)
    if args.subcommand == "model" and args.model_command == "download":
        return cmd_model_download(cfg)
    if args.subcommand == "doctor":
        return cmd_doctor(cfg, config_path)
    parser.error(f"unknown subcommand: {args.subcommand}")
    return 2  # unreachable


if __name__ == "__main__":
    sys.exit(main())
