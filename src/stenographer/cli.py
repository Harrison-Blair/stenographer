# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point and subcommand dispatch."""

from __future__ import annotations

# PYTHON_ARGCOMPLETE_OK
import os

if "_ARGCOMPLETE" in os.environ:  # completion hot path: skip the heavy imports below
    import argcomplete

    from stenographer._parser import build_parser

    argcomplete.autocomplete(build_parser())  # writes completions and exits

import contextlib
import fcntl
import logging
import logging.handlers
import pathlib
import shutil
import signal
import subprocess
import sys
from collections.abc import Sequence

import soundfile

from stenographer import __version__
from stenographer._parser import build_parser
from stenographer.asr.model import LazyModel, Model
from stenographer.asr.worker import Worker
from stenographer.audio.capture import Recorder
from stenographer.audio.feedback import CueName, Feedback
from stenographer.capabilities import Capabilities
from stenographer.config import Config
from stenographer.errors import UpdateError, fatal
from stenographer.hotkey.binding import HotkeyBinding
from stenographer.hotkey.listener import HotkeyListener
from stenographer.hotkey.state_machine import HotkeyStateMachine
from stenographer.notification import DesktopNotification
from stenographer.output.clipboard import ClipboardManager
from stenographer.output.inject import Injector
from stenographer.session import Session
from stenographer.update import (
    UpdateInfo,
    apply_update,
    check_for_update,
    detect_install_root,
    download_update,
    extract_to_staging,
    start_daemon,
    stop_daemon,
)

_CHANGELOG_BOX_WIDTH = 60

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


def _resolve_icon_root() -> pathlib.Path:
    """Return the directory holding the bundled icon.

    Mirrors :func:`_resolve_asset_root` but for ``assets/icons``.
    """
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return pathlib.Path(sys._MEIPASS) / "stenographer" / "assets" / "icons"
    return pathlib.Path(__file__).resolve().parent / "assets" / "icons"


_ICON_ROOT = _resolve_icon_root()


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
            logging.handlers.RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3),
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
    if one_shot or cfg.asr.mode == "eager":
        log.info("loading ASR model: %s", cfg.asr.model)
        model: Model | LazyModel = Model(cfg.asr)
    else:
        model = LazyModel(
            cfg.asr,
            idle_unload_seconds=cfg.asr.idle_unload_seconds or None,
        )
    worker = Worker(model)
    worker.start()
    if isinstance(model, LazyModel):
        model.attach_worker(worker)
    feedback = _build_feedback(cfg, caps)

    def _on_recorder_error(exc: Exception) -> None:
        log.error("recorder: %s", exc)
        with contextlib.suppress(Exception):
            feedback.play("error")

    recorder = Recorder(
        sample_rate=cfg.audio.sample_rate,
        frames_per_buffer=cfg.audio.frames_per_buffer,
        device=cfg.audio.input_device,
        on_error=_on_recorder_error,
        max_seconds=cfg.audio.max_recording_seconds,
        # Mid-recording silence flushing is a daemon (PTT/toggle) feature; the
        # one-shot processor stops after the first item, so disable it there.
        silence_detection=cfg.audio.silence_detection and not one_shot,
        silence_rms_threshold=cfg.audio.silence_rms_threshold,
        silence_duration_seconds=cfg.audio.silence_duration_seconds,
    )
    injector = Injector(
        available=caps.has_wtype,
        append_trailing_space=cfg.output.append_trailing_space,
        max_chars=cfg.output.max_chars,
    )
    clipboard = ClipboardManager(available=caps.has_wl_copy)
    notification = DesktopNotification(
        icon_path=_ICON_ROOT / "stenographer.png",
    )
    binding = HotkeyBinding.parse(cfg.hotkey.binding)
    cancel_binding = (
        HotkeyBinding.parse(cfg.hotkey.cancel_binding) if cfg.hotkey.cancel_binding else None
    )
    sm = HotkeyStateMachine(
        threshold_seconds=cfg.hotkey.toggle_threshold_seconds,
        double_tap_window_seconds=cfg.hotkey.double_tap_window_seconds,
    )
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
        lock=session.lock,
        cancel_binding=cancel_binding,
        on_discard=session.discard_recording,
        on_cancel=session.cancel_all,
    )
    session.start()
    session.attach_listener(listener)
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
    session.start_listener()
    _install_signal_handlers(session)
    log.info("session: daemon running (pid=%d)", os.getpid())
    if session.notification is not None:
        session.notification.show_startup(cfg.hotkey.binding)
    try:
        session.run()
    finally:
        session.stop()
        _release_single_instance_lock()
    return 0


def cmd_run_stop() -> int:
    """Stop any running daemon (systemd or direct). Best-effort."""
    # 1) Try systemd.
    if stop_daemon():
        print("stenographer: stopped systemd unit.", file=sys.stderr)
        return 0

    # 2) Fall back to the lock-file PID.
    if not _LOCK_PATH.exists():
        print("stenographer: no running daemon found.", file=sys.stderr)
        return 0

    try:
        pid_str = _LOCK_PATH.read_text().strip()
    except OSError:
        print("stenographer: cannot read lock file.", file=sys.stderr)
        return 1

    if not pid_str.isdigit():
        print("stenographer: lock file does not contain a valid PID.", file=sys.stderr)
        return 1

    pid = int(pid_str)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"stenographer: PID {pid} is not running; lock file is stale.", file=sys.stderr)
        _LOCK_PATH.unlink(missing_ok=True)
        return 0
    except PermissionError:
        print(f"stenographer: cannot signal PID {pid} (permission denied).", file=sys.stderr)
        return 1

    print(f"stenographer: sent SIGTERM to PID {pid}.", file=sys.stderr)
    return 0


def cmd_run_disable() -> int:
    """Disable (and stop) the systemd user unit. Warns if missing / already disabled."""
    unit_path = pathlib.Path.home() / ".config" / "systemd" / "user" / "stenographer.service"

    if shutil.which("systemctl") is None:
        print("stenographer: systemctl not available.", file=sys.stderr)
        return 1

    if not unit_path.is_file():
        print(f"stenographer: warning: systemd unit not found at {unit_path}", file=sys.stderr)
        return 0

    try:
        enabled = subprocess.run(
            ["systemctl", "--user", "is-enabled", "stenographer.service"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        print("stenographer: cannot run systemctl.", file=sys.stderr)
        return 1

    if enabled.returncode != 0:
        print("stenographer: already disabled.", file=sys.stderr)
        return 0

    subprocess.run(
        ["systemctl", "--user", "stop", "stenographer.service"],
        check=False,
    )
    subprocess.run(
        ["systemctl", "--user", "disable", "stenographer.service"],
        check=False,
    )
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        check=False,
    )
    print("stenographer: disabled systemd unit.", file=sys.stderr)
    return 0


def cmd_dictate(cfg: Config) -> int:
    caps = Capabilities.probe(cfg)
    if not (caps.has_mic and caps.has_asr_model):
        fatal("missing required capabilities: mic and/or asr-model")
    session = _build_session(cfg, caps, one_shot=True)
    session.start_listener()
    _install_signal_handlers(session)
    log.info("session: dictate mode armed; press the hotkey once")
    if session.notification is not None:
        session.notification.show_startup(cfg.hotkey.binding)
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


def _print_changelog(info: UpdateInfo) -> None:
    """Print ``info.release_notes`` in a bordered box to stderr.

    See ``spec/12-update.md`` "Display the change log" step. The body
    is taken verbatim from the GitHub release; if empty, a
    placeholder line is shown so the box is still framed.
    """
    rule = "=" * _CHANGELOG_BOX_WIDTH
    print(rule, file=sys.stderr)
    print(f"Release notes for v{info.latest_version}", file=sys.stderr)
    print(rule, file=sys.stderr)
    body = (info.release_notes or "").strip()
    if body:
        for line in body.splitlines():
            print(line, file=sys.stderr)
    else:
        print("(no release notes provided)", file=sys.stderr)
    print(rule, file=sys.stderr)
    print("", file=sys.stderr)


def cmd_update(
    cfg: Config,
    *,
    check: bool,
    yes: bool,
    no_restart: bool,
    prerelease: bool,
    repo: str | None,
) -> int:
    """Self-update subcommand. See ``spec/12-update.md``."""
    from dataclasses import replace

    from stenographer.update import acquire_update_lock

    lock_fd = acquire_update_lock()
    if lock_fd is None:
        print("stenographer: another update is in progress.", file=sys.stderr)
        return 1
    try:
        update_cfg = cfg.update
        if repo is not None:
            update_cfg = replace(update_cfg, repo=repo)

        try:
            info = check_for_update(update_cfg, prerelease=prerelease)
        except UpdateError as exc:
            fatal(str(exc), code=1)

        if info is None:
            print(f"stenographer is up to date (v{__version__}).", file=sys.stderr)
            return 0

        print(
            f"update available: {info.current_version} -> {info.latest_version}",
            file=sys.stderr,
        )
        _print_changelog(info)

        if check:
            return 0

        if not yes:
            print(f"Install v{info.latest_version}? [y/N] ", file=sys.stderr, end="")
            try:
                answer = input().strip().lower()
            except EOFError:
                print(
                    "\nupdate: no input available; pass --yes to install non-interactively.",
                    file=sys.stderr,
                )
                answer = ""
            if answer not in ("y", "yes"):
                print("update: cancelled", file=sys.stderr)
                return 0

        was_running = stop_daemon() if not no_restart else False

        try:
            tarball = download_update(info, update_cfg)
            install_root = detect_install_root()
            bundle = extract_to_staging(tarball, install_root)
            apply_update(bundle, install_root)
        except UpdateError as exc:
            fatal(str(exc), code=1)

        if not no_restart and was_running:
            started = start_daemon()
            if not started:
                print(
                    "update: installed, but `systemctl --user start` did not run; "
                    "start the daemon by hand.",
                    file=sys.stderr,
                )
                return 1

        print(f"Updated to v{info.latest_version}.", file=sys.stderr)
        return 0
    finally:
        os.close(lock_fd)


def cmd_devices() -> int:
    """List audio input devices for the ``audio.input_device`` config key."""
    import sounddevice

    try:
        devices = sounddevice.query_devices()
    except sounddevice.PortAudioError as exc:
        print(f"stenographer: cannot query audio devices: {exc}", file=sys.stderr)
        return 1
    try:
        default_index = sounddevice.default.device[0]
    except TypeError, IndexError:
        default_index = -1
    print("audio input devices (use the name or index as audio.input_device):")
    found = False
    for dev in devices:
        if dev.get("max_input_channels", 0) <= 0:
            continue
        found = True
        marker = "*" if dev.get("index") == default_index else " "
        print(f"  {marker} [{dev.get('index')}] {dev.get('name')}")
    if not found:
        print("  (none found)")
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
    if caps.has_mic:
        mic_name = cfg.audio.input_device or f"default: {Recorder.default_input_device_name()}"
        print(f"mic device:     {mic_name}")
    else:
        print("mic device:     NO  (recording disabled)")
    print(f"asr model:      {'yes' if caps.has_asr_model else 'NO  (transcription disabled)'}")
    print(f"asr.mode:       {cfg.asr.mode}")
    print(f"asr.idle_unload_seconds: {cfg.asr.idle_unload_seconds} (0 = disabled)")
    has_notify = DesktopNotification.probe()
    print(f"notify-send:    {'yes' if has_notify else 'NO  (desktop notification disabled)'}")
    fatal_cap = not (caps.has_input_group and caps.has_mic and caps.has_asr_model)
    return 78 if fatal_cap else 0


def main(argv: Sequence[str] | None = None) -> int:
    import multiprocessing

    import argcomplete

    multiprocessing.freeze_support()
    _configure_logging()
    parser = build_parser()
    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)
    if args.config is not None:
        os.environ["STENOGRAPHER_CONFIG"] = str(args.config)

    # Subcommands that don't need config.
    if args.subcommand == "run":
        if args.run_command == "stop":
            return cmd_run_stop()
        if args.run_command == "disable":
            return cmd_run_disable()
    if args.subcommand == "devices":
        return cmd_devices()

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
    if args.subcommand == "update":
        return cmd_update(
            cfg,
            check=args.check,
            yes=args.yes,
            no_restart=args.no_restart,
            prerelease=args.prerelease,
            repo=args.repo,
        )
    if args.subcommand == "doctor":
        return cmd_doctor(cfg, config_path)
    parser.error(f"unknown subcommand: {args.subcommand}")
    return 2  # unreachable


if __name__ == "__main__":
    sys.exit(main())
