# SPDX-License-Identifier: GPL-3.0-or-later
"""Ollama endpoint URLs and the loopback question. PURE: no I/O anywhere here.

The host is user configuration, so it is normalised rather than rejected: a
trailing slash, or a bare ``127.0.0.1:11434`` with no scheme, both name the
same server. :func:`is_loopback` answers the one privacy-relevant question
about it — whether a transcript sent to this host leaves the machine — for the
config validator, the daemon banner, and the setup wizard alike.
"""

from __future__ import annotations

#: Host names that resolve to this machine by definition rather than by lookup.
_LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"})


def normalize_host(host: str) -> str:
    """Return *host* with a lower-cased scheme and no trailing slash.

    Schemes are case-insensitive everywhere else, so ``HTTP://`` is folded
    rather than refused. The scheme is split off before any trimming: stripping
    slashes first turns ``http://`` into ``http:``, which then looks
    scheme-less and gets a second scheme prefixed onto it.
    """

    value = host.strip()
    if not value:
        return ""
    scheme, separator, rest = value.partition("://")
    if separator:
        scheme = scheme.casefold()
    else:
        scheme, rest = "http", value
    return f"{scheme}://{rest.rstrip('/')}"


def userinfo(host: str) -> str:
    """Credentials embedded in *host*, or ``""``. PURE."""

    _, _, rest = normalize_host(host).partition("://")
    return rest.split("/", 1)[0].rpartition("@")[0]


def authority(host: str) -> str:
    """The ``host[:port]`` of *host*, lower-cased and without credentials. PURE.

    What the banner reports: it identifies the server for a bug report without
    ever echoing a credential someone wrote into their config.
    """

    _, _, rest = normalize_host(host).partition("://")
    return rest.split("/", 1)[0].rpartition("@")[2].casefold()


def host_name(host: str) -> str:
    """The bare host name of *host*, without its port. PURE."""

    value = authority(host)
    if value.startswith("["):
        return value.partition("]")[0] + "]"
    return value.rpartition(":")[0] if ":" in value else value


def is_loopback(host: str) -> bool:
    """Whether a request to *host* stays on this machine.

    Conservative by construction: only the literal loopback spellings and the
    ``127.0.0.0/8`` block count. Anything else — a LAN address, a name that
    happens to resolve back here — is reported as remote, because the banner
    and the config comment must warn whenever they cannot prove otherwise.
    """

    name = host_name(host)
    if name in _LOOPBACK_NAMES:
        return True
    parts = name.split(".")
    return len(parts) == 4 and parts[0] == "127" and all(part.isdecimal() for part in parts)


def chat_url(host: str) -> str:
    """The native chat endpoint, which the refine request posts to."""

    return f"{normalize_host(host)}/api/chat"


def tags_url(host: str) -> str:
    """The installed-model listing, used to detect Ollama and size a pull."""

    return f"{normalize_host(host)}/api/tags"


def pull_url(host: str) -> str:
    """The streaming model pull, reached only from an explicit download."""

    return f"{normalize_host(host)}/api/pull"


def generate_url(host: str) -> str:
    """The generate endpoint, used only to warm and to unload a model."""

    return f"{normalize_host(host)}/api/generate"


def ps_url(host: str) -> str:
    """The running-model listing, asked before each utterance to tell a cold
    model from a warm one so a load is never charged against the reply budget."""

    return f"{normalize_host(host)}/api/ps"
