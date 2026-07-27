from __future__ import annotations

import json
from pathlib import Path

import pytest

from reconforge.close_workflow import load_close_checklist, write_close_checklist
from reconforge.io.structured import DEFAULT_STRUCTURED_DOCUMENT_POLICY


def _assert_safe_error(exc: pytest.ExceptionInfo[ValueError], message: str, path: Path) -> None:
    assert str(exc.value) == message
    assert path.name not in str(exc.value)


def _deep_yaml() -> str:
    lines = ["task:"]
    lines.extend(f"{'  ' * level}child:" for level in range(1, 66))
    lines.append(f"{'  ' * 66}value: 1")
    return "\n".join(lines) + "\n"


def test_valid_json_close_template_remains_compatible(tmp_path: Path) -> None:
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "CLOSE-JSON",
                        "title": "JSON template task",
                        "status": "In Progress",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )

    checklist_path = write_close_checklist(tmp_path / "close", template_path=template)
    checklist = load_close_checklist(checklist_path)

    assert checklist["tasks"][0]["task_id"] == "CLOSE-JSON"
    assert checklist["tasks"][0]["task_name"] == "JSON template task"
    assert checklist["tasks"][0]["status"] == "In Progress"


@pytest.mark.parametrize(
    "payload",
    [
        '{"version":1,"tasks":[],"tasks":[]}',
        '{"version":1,"tasks":[],"value":NaN}',
        "[" * 65 + "0" + "]" * 65,
    ],
    ids=["duplicate-key", "non-finite", "depth"],
)
def test_close_checklist_rejects_ambiguous_or_deep_json_safely(
    tmp_path: Path,
    payload: str,
) -> None:
    path = tmp_path / "close_checklist.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_close_checklist(path)

    _assert_safe_error(exc, "Close checklist JSON could not be parsed.", path)


def test_close_checklist_rejects_oversized_json_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "close_checklist.json"
    path.write_bytes(b" " * (DEFAULT_STRUCTURED_DOCUMENT_POLICY.max_file_bytes + 1))

    with pytest.raises(ValueError) as exc:
        load_close_checklist(path)

    _assert_safe_error(exc, "Close checklist JSON could not be parsed.", path)


@pytest.mark.parametrize(
    "payload",
    [
        "tasks: []\ntasks: []\n",
        _deep_yaml(),
        "anchor: &task []\ntasks:\n" + "  - *task\n" * 65,
        "tasks: !!python/object/apply:builtins.eval ['1 + 1']\n",
        "tasks: []\n---\ntasks: []\n",
    ],
    ids=["duplicate-key", "depth", "alias-budget", "unsafe-tag", "multiple-documents"],
)
def test_close_template_rejects_ambiguous_or_unsafe_yaml_safely(
    tmp_path: Path,
    payload: str,
) -> None:
    path = tmp_path / "sensitive-template.yaml"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        write_close_checklist(tmp_path / "close", template_path=path)

    _assert_safe_error(exc, "Close checklist template could not be parsed.", path)
