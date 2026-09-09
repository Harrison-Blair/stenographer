# SPDX-License-Identifier: GPL-3.0-or-later
"""Every log call in the package renders ``subsystem: event key=value ...``.

The format is the contract the log is read and grepped through, so it is
checked at the source: a template is either a literal in that shape, a
:func:`fmt_event` call with a literal subsystem and event, or a
:func:`log_failure` label. Seen to FAIL against the pre-format tree (``asr:
model loaded ...``, ``update check: fetch failed``, ``daemon: running
(pid=%d)`` and twenty others).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "stenographer"

_LEVELS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})
_LOGGERS = frozenset({"log", "logger"})
_NAME = r"[a-z][a-z0-9_]*"
# A value is one bare token, or — once ``fmt_event`` has had to quote a runtime
# value carrying whitespace — one double-quoted token with escapes inside it.
_VALUE = r'(?:"(?:[^"\\]|\\.)*"|\S+)'
_LABEL = re.compile(rf"{_NAME}: {_NAME}")
_TEMPLATE = re.compile(rf"{_NAME}: {_NAME}(?: {_NAME}={_VALUE})*")


def _literal(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _called_name(node: ast.Call) -> str | None:
    return node.func.id if isinstance(node.func, ast.Name) else None


def _offenses(source: str) -> list[str]:
    offenses: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if _called_name(node) == "log_failure" and len(node.args) >= 3:
            label = _literal(node.args[2])
            if label is None or not _LABEL.fullmatch(label):
                offenses.append(f"line {node.lineno}: log_failure label {ast.dump(node.args[2])}")
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _LEVELS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in _LOGGERS
        ):
            continue
        template = node.args[0]
        if isinstance(template, ast.Call) and _called_name(template) == "fmt_event":
            head = [_literal(arg) for arg in template.args[:2]]
            if len(head) != 2 or not all(part and re.fullmatch(_NAME, part) for part in head):
                offenses.append(f"line {node.lineno}: fmt_event needs a literal subsystem, event")
            continue
        # ``log_failure`` composes its own message from a validated label.
        if isinstance(template, ast.Call) and _called_name(template) == "_with_fields":
            continue
        text = _literal(template)
        if text is None:
            offenses.append(f"line {node.lineno}: template is not a literal or fmt_event(...)")
        elif not _TEMPLATE.fullmatch(text):
            offenses.append(f"line {node.lineno}: {text!r}")
    return offenses


def test_the_grammar_accepts_what_fmt_event_actually_renders():
    """The parser and the renderer must agree about a quoted value.

    ``fmt_event`` quotes any value carrying whitespace or a ``"``, so a grammar
    that only knows bare ``\\S+`` tokens would reject the very lines the
    renderer emits — and this file is the thing that decides whether a log line
    is well formed. Seen to FAIL against the bare-token-only ``_VALUE``.
    """
    from stenographer.utils.logging_setup import fmt_event

    spaced = fmt_event("deliver", "copy_failed", argv="xclip -selection clipboard", ok=0)
    assert _TEMPLATE.fullmatch(spaced), spaced

    quoted = fmt_event("helper", "failed", detail='he said "no"')
    assert _TEMPLATE.fullmatch(quoted), quoted

    bare = fmt_event("pipeline", "utterance", utt=1, gate="pass", total_ms=430.0)
    assert _TEMPLATE.fullmatch(bare), bare


def test_every_log_template_matches_the_event_format():
    offenders = {
        str(path.relative_to(SRC_ROOT)): offenses
        for path in sorted(SRC_ROOT.rglob("*.py"))
        if (offenses := _offenses(path.read_text(encoding="utf-8")))
    }
    assert not offenders, offenders


def test_dynamic_linux_log_fields_use_the_privacy_safe_renderers():
    """Dynamic device names and OS errors must never use logging interpolation.

    Seen to FAIL against the direct ``%s`` call sites: none of the five
    required formatter/failure lineages were present.
    """

    def shape(source: str) -> str:
        return ast.unparse(ast.parse(source).body[0])

    platform_root = SRC_ROOT / "platform" / "linux"
    paths = (platform_root / "hotkey.py", platform_root / "notify.py")
    actual = {
        (path.name, ast.unparse(node))
        for path in paths
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
    }
    expected = {
        (
            "hotkey.py",
            shape(
                "logger.info(fmt_event('hotkey', 'listening', "
                "device=device.path, name=device.name))"
            ),
        ),
        (
            "hotkey.py",
            shape("logger.info(fmt_event('hotkey', 'hotplug', device=path, name=device.name))"),
        ),
        (
            "hotkey.py",
            shape(
                "log_failure(logger, logging.WARNING, 'hotkey: device_lost', exc, "
                "safe=True, device=device.path)"
            ),
        ),
        (
            "notify.py",
            shape("log_failure(log, logging.DEBUG, 'notify: icon_unavailable', exc, safe=True)"),
        ),
        (
            "notify.py",
            shape("log_failure(log, logging.DEBUG, 'notify: send_failed', exc, safe=True)"),
        ),
    }

    assert expected <= actual, {"missing": sorted(expected - actual)}
