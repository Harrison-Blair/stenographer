# SPDX-License-Identifier: GPL-3.0-or-later
"""Real spawn, tuple IPC, timeout, shutdown, and log drain; no cached model needed."""

from io import StringIO

import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.logging.pipeline import (
    forward_worker_record,
    set_utterance,
    setup_logging,
    shutdown_logging,
)
from stenographer.lib.platform import current_platform

pytestmark = pytest.mark.integration


def test_native_asr_transport_contract_and_child_log_drain(tmp_path):
    stream = StringIO()
    shutdown_logging()
    setup_logging(env={"XDG_STATE_HOME": str(tmp_path)}, home=tmp_path, stderr=stream)
    process = None
    try:
        process = (
            current_platform()
            .asr_transport()
            .spawn(Config.defaults().asr, on_log=forward_worker_record)
        )
        assert process.pid and process.is_running() and process.exit_code is None
        with pytest.raises(TimeoutError):
            process.receive(0.01)
        set_utterance(99)
        # Deliberately exercise a real child's pre-load refusal: no model or
        # audio is needed to verify transport and privacy-safe log forwarding.
        process.send(("job", (), 7))
        response = process.receive(15)
        assert response[0:2] == ("error", "inference")
        process.close(graceful=True)
        process.close()
        assert not process.is_running() and process.exit_code == 0
        shutdown_logging()
        assert "utt=7 asr: job_failed" in stream.getvalue()
        assert "utt=99 asr: job_failed" not in stream.getvalue()
    finally:
        if process is not None:
            process.close()
        set_utterance(None)
        shutdown_logging()
