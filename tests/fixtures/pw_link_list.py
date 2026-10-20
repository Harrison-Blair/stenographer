# SPDX-License-Identifier: GPL-3.0-or-later
"""Sanitized real `pw-link -l` output captured for the monitor-link test."""

PW_LINK_LIST = """studio:monitor_AUX0
  |-> stenographer-system-capture:input_FL
studio:monitor_AUX1
  |-> stenographer-system-capture:input_FR
studio:playback_AUX0
  |<- spotify:output_FL
  |<- Firefox:output_FL
studio:playback_AUX1
  |<- spotify:output_FR
  |<- Firefox:output_FR
microphone:capture_FL
  |-> stenographer-mic:input_FL
microphone:capture_FR
  |-> stenographer-mic:input_FR
stenographer-system-capture:input_FL
  |<- studio:monitor_AUX0
stenographer-system-capture:input_FR
  |<- studio:monitor_AUX1
spotify:output_FL
  |-> studio:playback_AUX0
spotify:output_FR
  |-> studio:playback_AUX1
stenographer-mic:input_FL
  |<- microphone:capture_FL
stenographer-mic:input_FR
  |<- microphone:capture_FR
Firefox:output_FL
  |-> studio:playback_AUX0
Firefox:output_FR
  |-> studio:playback_AUX1
"""
