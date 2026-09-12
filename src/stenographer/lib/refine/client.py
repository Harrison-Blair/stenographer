# SPDX-License-Identifier: GPL-3.0-or-later
"""The only code in the project that talks to Ollama.

Stdlib ``urllib`` with the import inside each function, exactly as
``lib/updates/notice.py`` does it: no new runtime dependency, and nothing is
imported at all on a machine that never enables the stage.

Every request here is local by default (``http://127.0.0.1:11434``). The one
request that carries transcript text is :func:`post_chat`; the rest move model
names and byte counts only. No function logs a request or a response body.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from stenographer.lib.refine.endpoints import (
    chat_url,
    generate_url,
    ps_url,
    pull_url,
    qualify_tag,
    tags_url,
)
from stenographer.lib.refine.errors import RefineError, RefineTimeoutError, RefineTransportError
from stenographer.lib.refine.request import USER_AGENT, build_unload_body, build_warm_body, encode

if TYPE_CHECKING:
    from collections.abc import Callable

#: Metadata calls answer instantly on a live server and must not hang a wizard.
PROBE_TIMEOUT_SECONDS = 5.0
#: A cold model can take a while to load into VRAM before it answers at all.
WARM_TIMEOUT_SECONDS = 300.0
#: A pull is a multi-gigabyte download with its own progress; only a stall
#: between chunks should end it.
PULL_READ_TIMEOUT_SECONDS = 300.0
#: Unload runs during shutdown and must never hold it up: a server that has
#: already gone is the common case, not an exception.
UNLOAD_TIMEOUT_SECONDS = 2.0


def _translate(exc: Exception) -> RefineError:
    """Map one transport failure onto this package's vocabulary. PURE.

    The single place that decides what escapes this module. Reading a response
    body fails differently from opening it — a reset peer, a stalled read, a
    malformed chunked encoding — and ``http.client`` raises ``HTTPException``,
    which is *not* an ``OSError``, so catching ``OSError`` alone lets it
    through as a traceback.
    """

    import http.client
    import urllib.error

    if isinstance(exc, urllib.error.HTTPError):
        return RefineTransportError(f"ollama returned HTTP {exc.code}")
    if isinstance(exc, TimeoutError):
        return RefineTimeoutError("ollama did not answer in time")
    if isinstance(exc, urllib.error.URLError):
        # ``URLError`` wraps the socket failure, so a timeout arrives here
        # rather than above whenever the connect phase is what expired.
        if isinstance(exc.reason, TimeoutError):
            return RefineTimeoutError("ollama did not answer in time")
        return RefineTransportError("ollama could not be reached")
    if isinstance(exc, http.client.HTTPException | OSError):
        return RefineTransportError("ollama could not be reached")
    raise exc


def _translated(exc: Exception) -> RefineError:
    """``_translate``, but a ``RefineError`` passes straight through."""

    return exc if isinstance(exc, RefineError) else _translate(exc)


def _post(url: str, body: dict[str, object], timeout: float):
    """Open one POST and hand back the live response object."""

    import urllib.request

    request = urllib.request.Request(
        url,
        data=encode(body),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except Exception as exc:
        raise _translate(exc) from exc


def post_chat(host: str, body: dict[str, object], *, timeout: float) -> bytes:
    """POST one chat request and read the whole reply.

    Raises only :class:`RefineError`: opening the request and reading its body
    both go through :func:`_translate`, so a reset peer, a stalled read and an
    ``http.client.HTTPException`` all arrive at the refiner as a classified
    failure rather than as a traceback.
    """

    try:
        with _post(chat_url(host), body, timeout) as response:
            return response.read()
    except Exception as exc:
        raise _translated(exc) from exc


def _model_listing(url: str, *, timeout: float) -> list[dict]:
    """GET one of Ollama's ``{"models": [...]}`` listings, or ``[]``.

    Returning a list rather than raising is deliberate: every caller is asking
    "is there an Ollama here, and what does it have?", for which an unreachable
    host and an empty server are the same answer.
    """

    import urllib.request

    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except Exception:
        return []
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    return [entry for entry in models if isinstance(entry, dict)]


def _listed_names(entries: list[dict]) -> list[str]:
    """The tags a listing names, under either key Ollama uses, sorted. PURE."""

    names = {str(entry[key]) for entry in entries for key in ("name", "model") if key in entry}
    return sorted(names)


def installed_models(host: str, *, timeout: float = PROBE_TIMEOUT_SECONDS) -> list[dict]:
    """Every model ``/api/tags`` reports, or ``[]`` when nothing answers."""

    return _model_listing(tags_url(host), timeout=timeout)


def installed_model_names(host: str, *, timeout: float = PROBE_TIMEOUT_SECONDS) -> list[str]:
    """The model tags installed on *host*, sorted, or ``[]``."""

    names = {
        entry["name"]
        for entry in installed_models(host, timeout=timeout)
        if isinstance(entry.get("name"), str)
    }
    return sorted(names)


def running_model_names(host: str, *, timeout: float = PROBE_TIMEOUT_SECONDS) -> list[str]:
    """The model tags ``/api/ps`` reports as resident right now, or ``[]``."""

    return _listed_names(_model_listing(ps_url(host), timeout=timeout))


def is_model_loaded(host: str, model: str, *, timeout: float = PROBE_TIMEOUT_SECONDS) -> bool:
    """Whether *model* is resident on *host* at this moment.

    A server that cannot answer reads as "not loaded". That is the safe error:
    the caller then warms, and the warm — which may raise — is what reports
    the real failure. A false "not loaded" costs one no-token generate that a
    resident model answers immediately.
    """

    return qualify_tag(model) in running_model_names(host, timeout=timeout)


def installed_model_bytes(
    host: str, model: str, *, timeout: float = PROBE_TIMEOUT_SECONDS
) -> int | None:
    """The on-disk size Ollama reports for *model*, or ``None`` if absent.

    Both sides are qualified before comparing: a bare config value must
    still find a fully-tagged listing, and — should a listing ever report a
    bare name — the reverse must match too, rather than silently narrowing
    to an exact string match.
    """

    target = qualify_tag(model)
    for entry in installed_models(host, timeout=timeout):
        name, listed = entry.get("name"), entry.get("model")
        matches = (isinstance(name, str) and qualify_tag(name) == target) or (
            isinstance(listed, str) and qualify_tag(listed) == target
        )
        if matches:
            size = entry.get("size")
            if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
                return size
    return None


def pull_model(
    host: str,
    model: str,
    *,
    on_progress: Callable[[str], None] | None = None,
    timeout: float = PULL_READ_TIMEOUT_SECONDS,
) -> None:
    """Stream ``/api/pull`` to completion, reporting each status line.

    Ollama answers with one JSON object per line and ends a successful pull
    with a terminal ``{"status": "success"}`` line. An ``{"error": ...}``
    line always ends the pull, whether or not a caller is watching progress —
    the check runs on every line, not only when ``on_progress`` is set. A
    line that fails to parse is skipped rather than ending a multi-gigabyte
    download, but a stream that runs out without ever reporting success is
    itself a failure: nothing short of that line confirms the model actually
    landed on disk.
    """

    body = {"model": model, "stream": True}
    succeeded = False
    try:
        with _post(pull_url(host), body, timeout) as response:
            # Reading the stream is where a multi-gigabyte download actually
            # breaks, so it is inside the translation too, not just the open.
            for line in response:
                text = line.decode("utf-8", "replace").strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                if isinstance(record.get("error"), str):
                    raise RefineTransportError("ollama refused the pull")
                if record.get("status") == "success":
                    succeeded = True
                if on_progress is not None:
                    on_progress(pull_progress_line(record))
        if not succeeded:
            raise RefineTransportError("ollama ended the pull without confirming success")
    except Exception as exc:
        raise _translated(exc) from exc


def pull_progress_line(record: dict) -> str:
    """Render one streamed pull record as a short status line. PURE."""

    status = record.get("status")
    status_text = status if isinstance(status, str) else "pulling"
    completed = record.get("completed")
    total = record.get("total")
    if isinstance(completed, int) and isinstance(total, int) and total > 0:
        return f"{status_text} {100 * completed // total}%"
    return status_text


def warm_model(
    host: str, model: str, *, keep_alive: int, timeout: float = WARM_TIMEOUT_SECONDS
) -> None:
    """Load *model* and hold it for *keep_alive*. Raises only RefineError.

    The default budget suits the background warm at daemon start, which nobody
    is waiting on. An utterance waiting for a cold model passes a shorter one.
    """

    try:
        with _post(
            generate_url(host), build_warm_body(model=model, keep_alive=keep_alive), timeout
        ) as response:
            response.read()
    except Exception as exc:
        raise _translated(exc) from exc


def unload_model(host: str, model: str) -> None:
    """Ask Ollama to release *model* now. Raises only RefineError."""

    try:
        with _post(
            generate_url(host), build_unload_body(model=model), UNLOAD_TIMEOUT_SECONDS
        ) as response:
            response.read()
    except Exception as exc:
        raise _translated(exc) from exc
