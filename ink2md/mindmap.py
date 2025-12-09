"""Mindmap data structures and FreeMind serialization helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class MindmapValidationError(ValueError):
    """Raised when a mindmap payload is malformed."""


@dataclass(slots=True)
class MindmapNode:
    """Single node within a mindmap tree."""

    text: str
    children: List["MindmapNode"] = field(default_factory=list)
    link: Optional[str] = None
    color: Optional[str] = None
    priority: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MindmapNode":
        if not isinstance(data, dict):
            raise MindmapValidationError("Node payload must be a mapping")

        unexpected = set(data.keys()) - {"text", "children", "link", "color", "priority"}
        if unexpected:
            raise MindmapValidationError(
                f"Unexpected keys in node payload: {', '.join(sorted(unexpected))}"
            )

        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            raise MindmapValidationError("Each node must include non-empty 'text'")

        children_data = data.get("children", [])
        if children_data is None:
            children_data = []
        if not isinstance(children_data, list):
            raise MindmapValidationError("'children' must be a list when provided")

        children = [cls.from_dict(child) for child in children_data]

        link = data.get("link")
        if link is not None and not isinstance(link, str):
            raise MindmapValidationError("'link' must be a string when provided")

        color = data.get("color")
        if color is not None and not isinstance(color, str):
            raise MindmapValidationError("'color' must be a string when provided")

        priority_raw = data.get("priority")
        priority: Optional[int] = None
        if priority_raw is not None:
            if isinstance(priority_raw, int):
                priority = priority_raw
            elif isinstance(priority_raw, str) and priority_raw.strip().isdigit():
                priority = int(priority_raw.strip())
            else:
                raise MindmapValidationError(
                    "'priority' must be an integer or string-encoded integer"
                )

        return cls(
            text=text.strip(),
            children=children,
            link=link.strip() if isinstance(link, str) else None,
            color=color.strip() if isinstance(color, str) else None,
            priority=priority,
        )


@dataclass(slots=True)
class Mindmap:
    """Top-level wrapper for a mindmap."""

    root: MindmapNode

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "Mindmap":
        if not isinstance(data, dict):
            raise MindmapValidationError("Mindmap payload must be a mapping")
        if "root" not in data:
            raise MindmapValidationError("Mindmap payload must include a 'root' object")
        root_data = data["root"]
        if not isinstance(root_data, dict):
            raise MindmapValidationError("'root' must be an object")
        root_node = MindmapNode.from_dict(root_data)
        return cls(root=root_node)

    @classmethod
    def from_json(cls, raw_json: str) -> "Mindmap":
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise MindmapValidationError("Mindmap JSON could not be parsed") from exc
        return cls.from_mapping(parsed)


def serialize_to_freemind(mindmap: Mindmap) -> str:
    """Render a Mindmap into FreeMind XML."""

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<map version="1.0.1">']
    lines.append(_serialize_node(mindmap.root, indent=2))
    lines.append("</map>")
    return "\n".join(lines)


def _serialize_node(node: MindmapNode, *, indent: int) -> str:
    pad = " " * indent
    attributes = [("TEXT", node.text)]
    if node.link:
        attributes.append(("LINK", node.link))
    if node.color:
        attributes.append(("COLOR", node.color))
    if node.priority is not None:
        attributes.append(("PRIORITY", str(node.priority)))

    attr_text = " ".join(f'{key}="{_escape(value)}"' for key, value in attributes)
    if not node.children:
        return f"{pad}<node {attr_text}/>"

    children_xml = [
        _serialize_node(child, indent=indent + 2) for child in node.children
    ]
    children_block = "\n".join(children_xml)
    closing_pad = " " * indent
    return f"{pad}<node {attr_text}>\n{children_block}\n{closing_pad}</node>"


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


__all__ = ["Mindmap", "MindmapNode", "MindmapValidationError", "serialize_to_freemind"]
