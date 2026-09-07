# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure shared desktop form and analytics adapters."""

import pytest

from stenographer.config import ConfigError
from stenographer.settings import ConfigDocument
from stenographer_desktop.services import comparison_rows, edited_config, flatten, histogram_rows


def test_form_validation_preserves_unknown_content_and_rejects_invalid_values():
    document = ConfigDocument.loads(
        '# user comment\n[stenographer.feedback]\nmute = false # quiet\nfuture = "kept"\n'
    )
    config = edited_config(document, {"feedback.mute": True, "audio.max_recording_seconds": "120"})
    rendered = document.render(config)
    assert "mute = true # quiet" in rendered
    assert 'future = "kept"' in rendered
    assert "# user comment" in rendered
    assert config.audio.max_recording_seconds == 120
    with pytest.raises(ConfigError):
        edited_config(document, {"audio.max_recording_seconds": "-1"})
    with pytest.raises(ConfigError):
        edited_config(document, {"audio.max_recording_seconds": "not-a-number"})


def test_comparison_uses_raw_measurements_and_preserves_missing():
    records = [
        {"context": {"model": "one"}, "metrics": {"decode_ms": 10}},
        {"context": {"model": "one"}, "metrics": {"decode_ms": 30}},
        {"context": {"model": "one"}, "metrics": {}},
        {"context": {"model": "two"}, "metrics": {}},
    ]
    assert comparison_rows(records, "model", "decode_ms") == [
        ("one", 2, 1, 20, 30, 30),
        ("two", 0, 1, None, None, None),
    ]
    assert sum(count for _, count in histogram_rows(records, "decode_ms")) == 2
    assert histogram_rows(records, "capture_s") == []
    assert histogram_rows(records[:1], "decode_ms") == [("10", 1)]
    assert flatten({"unknown": None, "zero": 0}) == [("unknown", "Unavailable"), ("zero", "0")]
