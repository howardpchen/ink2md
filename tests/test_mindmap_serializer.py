"""Mindmap serialization and validation tests."""

from __future__ import annotations

from ink2md.mindmap import Mindmap, MindmapNode, serialize_to_freemind


def test_serialize_to_freemind_snapshot() -> None:
    mindmap = Mindmap(
        root=MindmapNode(
            text="Central Idea",
            link="https://example.com/root",
            color="#FF0000",
            priority=1,
            children=[
                MindmapNode(
                    text="Branch One",
                    children=[
                        MindmapNode(text="Leaf A1", priority=3),
                        MindmapNode(text="Leaf A2"),
                    ],
                ),
                MindmapNode(text="Branch Two", link="https://example.com/branch-two"),
            ],
        )
    )

    xml = serialize_to_freemind(mindmap)

    assert xml == (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<map version=\"1.0.1\">\n"
        "  <node TEXT=\"Central Idea\" LINK=\"https://example.com/root\" COLOR=\"#FF0000\" PRIORITY=\"1\">\n"
        "    <node TEXT=\"Branch One\">\n"
        "      <node TEXT=\"Leaf A1\" PRIORITY=\"3\"/>\n"
        "      <node TEXT=\"Leaf A2\"/>\n"
        "    </node>\n"
        "    <node TEXT=\"Branch Two\" LINK=\"https://example.com/branch-two\"/>\n"
        "  </node>\n"
        "</map>"
    )


def test_mindmap_from_json_coerces_priority() -> None:
    payload = (
        '{\n'
        '  "root": {\n'
        '    "text": "Root",\n'
        '    "children": [\n'
        '      {"text": "Child", "priority": "2", "children": []}\n'
        "    ]\n"
        "  }\n"
        "}"
    )

    mindmap = Mindmap.from_json(payload)

    assert mindmap.root.text == "Root"
    assert mindmap.root.children[0].priority == 2
