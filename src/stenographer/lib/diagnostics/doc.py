# SPDX-License-Identifier: GPL-3.0-or-later
"""Host diagnostics, analytics instrumentation, and optional capability checks.

- additional_checks.py: Probe optional PipeWire, live-model, and FFmpeg capabilities.
- capabilities.py: Collect and evaluate the required startup capabilities.
- capability_result.py: Store the required capability probe results.
- collection.py: Keep analytics collection fail-open.
- context.py: Build privacy-safe analytics context.
- session.py: Connect configuration and host services to analytics sessions.
"""
