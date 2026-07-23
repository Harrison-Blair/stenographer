# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import patch

import pytest


def _fake_check_for_update(info: Any) -> Any:
    def _fn(cfg: Any, **kwargs: Any) -> Any:
        return info

    return _fn


def _info(
    version: str = "0.7.0",
    *,
    release_notes: str = "notes",
) -> Any:
    from stenographer.update import UpdateInfo

    return UpdateInfo(
        current_version="0.6.0",
        latest_version=version,
        tag_name=f"v{version}",
        asset_url="https://example.invalid/tarball",
        asset_size=1024,
        sha256_url="https://example.invalid/sha",
        release_notes=release_notes,
        prerelease=False,
    )


def test_cli_update_check_exits_zero(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from stenographer.cli import main

    monkeypatch.setattr("sys.argv", ["stenographer", "update", "--check"])
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "y")
    with patch("stenographer.cli.check_for_update", _fake_check_for_update(_info())):
        rc = main()
    assert rc == 0
    captured = capsys.readouterr()
    assert "update available" in captured.err


def test_cli_update_check_up_to_date(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from stenographer.cli import main

    monkeypatch.setattr("sys.argv", ["stenographer", "update", "--check"])
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "missing.toml"))
    with patch("stenographer.cli.check_for_update", lambda *a, **kw: None):
        rc = main()
    assert rc == 0
    assert "up to date" in capsys.readouterr().err


def test_cli_update_no_yes_decline_exits_zero(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from stenographer.cli import main

    monkeypatch.setattr("sys.argv", ["stenographer", "update"])
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "n")
    with (
        patch("stenographer.cli.check_for_update", _fake_check_for_update(_info())),
        patch("stenographer.cli.detect_install_root", return_value=tmp_path / "stenographer"),
        patch("stenographer.cli.download_update") as dl,
        patch("stenographer.cli.extract_to_staging") as ex,
        patch("stenographer.cli.apply_update") as ap,
        patch("stenographer.cli.stop_daemon") as stop,
        patch("stenographer.cli.start_daemon") as start,
    ):
        rc = main()
    assert rc == 0
    dl.assert_not_called()
    ex.assert_not_called()
    ap.assert_not_called()
    stop.assert_not_called()
    start.assert_not_called()
    captured = capsys.readouterr()
    assert "cancelled" in captured.err


def test_cli_update_yes_skips_prompt(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from stenographer.cli import main

    monkeypatch.setattr("sys.argv", ["stenographer", "update", "--yes", "--no-restart"])
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "missing.toml"))

    def _no_input(*a: Any, **kw: Any) -> Any:
        raise AssertionError("input() should not be called with --yes")

    monkeypatch.setattr("builtins.input", _no_input)

    fake_tarball = tmp_path / "stenographer-0.7.0.tar.gz"
    fake_tarball.write_bytes(b"fake")

    fake_install_root = tmp_path / "opt" / "stenographer"
    fake_install_root.mkdir(parents=True)
    (fake_install_root / "_internal").mkdir()

    fake_bundle = fake_install_root / "stenographer"
    with (
        patch("stenographer.cli.check_for_update", _fake_check_for_update(_info())),
        patch("stenographer.cli.download_update", return_value=fake_tarball),
        patch("stenographer.cli.detect_install_root", return_value=fake_install_root),
        patch("stenographer.cli.extract_to_staging", return_value=fake_bundle),
        patch("stenographer.cli.apply_update") as ap,
        patch("stenographer.cli.stop_daemon") as stop,
    ):
        rc = main()
    assert rc == 0
    ap.assert_called_once()
    stop.assert_not_called()
    captured = capsys.readouterr()
    assert "Updated to v0.7.0" in captured.err


def test_cli_update_repo_override(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from stenographer.cli import main

    monkeypatch.setattr("sys.argv", ["stenographer", "update", "--check", "--repo", "other/repo"])
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "missing.toml"))

    seen: dict[str, Any] = {}

    def _capture(cfg: Any, **kwargs: Any) -> Any:
        seen["repo"] = cfg.repo
        seen["allow_dev_downgrade"] = kwargs.get("allow_dev_downgrade", False)
        return _info()

    with patch("stenographer.cli.check_for_update", _capture):
        rc = main()
    assert rc == 0
    assert seen["repo"] == "other/repo"
    # The explicit `update` command opts into the dev-build escape hatch.
    assert seen["allow_dev_downgrade"] is True


# ---------------------------------------------------------------------------
# Changelog display
# ---------------------------------------------------------------------------


def test_cli_update_check_prints_changelog_box(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from stenographer.cli import main

    body = "abc1234 fix hotkey double-fire\ndef5678 bump faster-whisper to 1.0.0"
    monkeypatch.setattr("sys.argv", ["stenographer", "update", "--check"])
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "missing.toml"))
    with patch(
        "stenographer.cli.check_for_update",
        _fake_check_for_update(_info(release_notes=body)),
    ):
        rc = main()
    assert rc == 0
    captured = capsys.readouterr()
    err = captured.err
    assert "update available" in err
    assert "Release notes for v0.7.0" in err
    assert "abc1234 fix hotkey double-fire" in err
    assert "def5678 bump faster-whisper to 1.0.0" in err
    assert "=" * 60 in err
    # --check must not perform the install, so the post-install report
    # is absent.
    assert "Updated to v0.7.0" not in err


def test_cli_update_interactive_prints_changelog_before_prompt(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from stenographer.cli import main

    body = "fix: cap buffer at end of recording"
    monkeypatch.setattr("sys.argv", ["stenographer", "update"])
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "n")
    with (
        patch(
            "stenographer.cli.check_for_update",
            _fake_check_for_update(_info(release_notes=body)),
        ),
        patch("stenographer.cli.detect_install_root", return_value=tmp_path / "stenographer"),
        patch("stenographer.cli.download_update") as dl,
        patch("stenographer.cli.extract_to_staging") as ex,
        patch("stenographer.cli.apply_update") as ap,
        patch("stenographer.cli.stop_daemon") as stop,
        patch("stenographer.cli.start_daemon") as start,
    ):
        rc = main()
    assert rc == 0
    dl.assert_not_called()
    ex.assert_not_called()
    ap.assert_not_called()
    stop.assert_not_called()
    start.assert_not_called()
    err = capsys.readouterr().err
    assert "Release notes for v0.7.0" in err
    assert "fix: cap buffer at end of recording" in err
    # Changelog must appear before the prompt and the cancellation line.
    assert err.index("Release notes for v0.7.0") < err.index("[y/N]")
    assert err.index("Release notes for v0.7.0") < err.index("cancelled")
    # The changelog body must not be re-printed after a successful
    # install (per the chosen design: before the prompt only).
    assert err.count("fix: cap buffer at end of recording") == 1


def test_cli_update_changelog_empty_shows_placeholder(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from stenographer.cli import main

    monkeypatch.setattr("sys.argv", ["stenographer", "update", "--check"])
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "missing.toml"))
    with patch(
        "stenographer.cli.check_for_update",
        _fake_check_for_update(_info(release_notes="")),
    ):
        rc = main()
    assert rc == 0
    err = capsys.readouterr().err
    assert "Release notes for v0.7.0" in err
    assert "(no release notes provided)" in err
    assert "=" * 60 in err


def test_cli_update_successful_install_does_not_reprint_changelog(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from stenographer.cli import main

    body = "release note that should only appear once"
    monkeypatch.setattr("sys.argv", ["stenographer", "update", "--yes", "--no-restart"])
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setattr("builtins.input", lambda *a, **kw: (_ for _ in ()).throw(AssertionError))

    fake_tarball = tmp_path / "stenographer-0.7.0.tar.gz"
    fake_tarball.write_bytes(b"fake")
    fake_install_root = tmp_path / "opt" / "stenographer"
    fake_install_root.mkdir(parents=True)
    (fake_install_root / "_internal").mkdir()
    fake_bundle = fake_install_root / "stenographer"

    with (
        patch(
            "stenographer.cli.check_for_update",
            _fake_check_for_update(_info(release_notes=body)),
        ),
        patch("stenographer.cli.download_update", return_value=fake_tarball),
        patch("stenographer.cli.detect_install_root", return_value=fake_install_root),
        patch("stenographer.cli.extract_to_staging", return_value=fake_bundle),
        patch("stenographer.cli.apply_update") as ap,
    ):
        rc = main()
    assert rc == 0
    ap.assert_called_once()
    err = capsys.readouterr().err
    # Header appears once.
    assert err.count("Release notes for v0.7.0") == 1
    # Body appears once.
    assert err.count("release note that should only appear once") == 1
    # Changelog sits before the post-install report.
    assert err.index("Release notes for v0.7.0") < err.index("Updated to v0.7.0.")


def test_cli_update_unsupported_install_fails_before_side_effects(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from stenographer.cli import main
    from stenographer.errors import UpdateError

    monkeypatch.setattr("sys.argv", ["stenographer", "update", "--yes"])
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "missing.toml"))
    with (
        patch("stenographer.cli.check_for_update", _fake_check_for_update(_info())),
        patch(
            "stenographer.cli.detect_install_root",
            side_effect=UpdateError(
                "update: self-update is only supported for the onedir binary install; "
                "use pip/pipx to upgrade this installation"
            ),
        ),
        patch("stenographer.cli.download_update") as download,
        patch("stenographer.cli.stop_daemon") as stop,
        pytest.raises(SystemExit, match="1"),
    ):
        main()
    download.assert_not_called()
    stop.assert_not_called()
    assert "use pip/pipx to upgrade" in caplog.text
