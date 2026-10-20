# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspect PipeWire links for the Linux system-audio capture stream."""

from __future__ import annotations

import json
import shutil

_CAPTURE_NODE = "stenographer-system-capture"


def parse_pw_link_output(output: str) -> tuple[set[str], set[tuple[str, str]]]:
    ports: set[str] = set()
    links: set[tuple[str, str]] = set()
    current_port: str | None = None
    for line in output.splitlines():
        if line and not line[0].isspace():
            current_port = line.strip()
            ports.add(current_port)
            continue
        fields = line.split(maxsplit=1)
        if current_port is None or len(fields) != 2:
            continue
        direction, endpoint = fields
        if direction == "|->":
            links.add((current_port, endpoint))
            ports.add(endpoint)
        elif direction == "|<-":
            links.add((endpoint, current_port))
            ports.add(endpoint)
    return ports, links


def parse_pw_dump_output(output: str) -> tuple[set[str], set[tuple[str, str]]]:
    try:
        objects = json.loads(output)
    except (TypeError, ValueError):
        return set(), set()
    if not isinstance(objects, list):
        return set(), set()

    nodes: dict[str, str] = {}
    ports_by_id: dict[str, tuple[str, str]] = {}
    raw_links: list[dict] = []
    for item in objects:
        if not isinstance(item, dict):
            continue
        info = item.get("info")
        if not isinstance(info, dict):
            continue
        props = info.get("props")
        if not isinstance(props, dict):
            props = {}
        item_type = item.get("type")
        item_id = str(item.get("id"))
        if item_type == "PipeWire:Interface:Node":
            node_name = props.get("node.name")
            if isinstance(node_name, str):
                nodes[item_id] = node_name
        elif item_type == "PipeWire:Interface:Port":
            node_id = props.get("node.id")
            port_name = props.get("port.name")
            if node_id is not None and isinstance(port_name, str):
                ports_by_id[item_id] = str(node_id), port_name
        elif item_type == "PipeWire:Interface:Link":
            raw_links.append(info)

    ports: set[str] = set()
    links: set[tuple[str, str]] = set()
    for info in raw_links:
        props = info.get("props")
        if not isinstance(props, dict):
            props = {}
        output_node = info.get("output-node-id", props.get("link.output.node"))
        output_port = info.get("output-port-id", props.get("link.output.port"))
        input_node = info.get("input-node-id", props.get("link.input.node"))
        input_port = info.get("input-port-id", props.get("link.input.port"))
        source = _pw_dump_endpoint(output_node, output_port, nodes, ports_by_id)
        target = _pw_dump_endpoint(input_node, input_port, nodes, ports_by_id)
        if source is not None and target is not None:
            links.add((source, target))
            ports.update((source, target))
    ports.update(
        f"{nodes[node_id]}:{port_name}"
        for node_id, port_name in ports_by_id.values()
        if node_id in nodes
    )
    return ports, links


def _pw_dump_endpoint(
    node_id: object,
    port_id: object,
    nodes: dict[str, str],
    ports_by_id: dict[str, tuple[str, str]],
) -> str | None:
    port = ports_by_id.get(str(port_id))
    if port is None:
        return None
    actual_node_id, port_name = port
    if str(node_id) != actual_node_id or actual_node_id not in nodes:
        return None
    return f"{nodes[actual_node_id]}:{port_name}"


def link_inspector() -> tuple[str, str] | None:
    pw_link = shutil.which("pw-link")
    if pw_link is not None:
        return "pw-link", pw_link
    pw_dump = shutil.which("pw-dump")
    if pw_dump is not None:
        return "pw-dump", pw_dump
    return None


def has_sink_monitor_links(
    ports: set[str], links: set[tuple[str, str]], sink: str, capture_node: str = _CAPTURE_NODE
) -> bool:
    capture_inputs = {port for port in ports if port.startswith(f"{capture_node}:input_")}
    if not capture_inputs:
        return False
    for capture_input in capture_inputs:
        sources = {source for source, target in links if target == capture_input}
        if not sources or any(not source.startswith(f"{sink}:monitor_") for source in sources):
            return False
    return True
