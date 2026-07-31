"""Evidence Graph Schema and Lineage Verification Engine.

Transforms flat evidence binders into a traceable, queryable Evidence Graph
with strict node types, directed edge relationships, redaction support, and
SHA-256 integrity manifests.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, Field

from reconforge.utils.time import utc_now_text

NodeType = Literal[
    "source_file",
    "source_record",
    "import_job",
    "validation_result",
    "normalization_result",
    "rule_version",
    "candidate",
    "match_decision",
    "exception",
    "review_action",
    "approval",
    "report",
    "export",
    "external_reference",
]

EdgeRelation = Literal[
    "derived_from",
    "validated_by",
    "normalized_by",
    "candidate_for",
    "matched_to",
    "rejected_by",
    "reviewed_by",
    "approved_by",
    "included_in",
    "supersedes",
    "reversed_by",
]


class EvidenceGraphNode(BaseModel):
    """A single node in the evidence lineage graph."""

    id: str
    node_type: NodeType
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)
    data_classification: str = "financial-sensitive"
    retention_policy: str = "local-retention-standard"
    redaction_mask: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_text)
    node_hash: str = ""

    def model_post_init(self, __context: Any) -> None:
        redaction_mask = sorted(set(self.redaction_mask))
        object.__setattr__(self, "redaction_mask", redaction_mask)
        if not self.node_hash:
            object.__setattr__(self, "node_hash", self.compute_node_hash())

    @staticmethod
    def _redact_fields(payload: dict[str, Any], masks: list[str]) -> None:
        """Mutate the payload in-place applying dotted-path redaction masks."""

        for mask in masks:
            if not mask:
                continue
            cursor = payload
            parts = mask.split(".")
            for index, part in enumerate(parts):
                if index == len(parts) - 1:
                    if isinstance(cursor, dict) and part in cursor:
                        cursor[part] = "***redacted***"
                    break
                if not isinstance(cursor, dict) or part not in cursor:
                    break
                cursor = cursor[part]

    def _canonical_payload(self, *, redact: bool = False) -> dict[str, Any]:
        payload = deepcopy(self.payload)
        if redact and self.redaction_mask:
            copied = deepcopy(payload)
            self._redact_fields(copied, self.redaction_mask)
            payload = copied

        return {
            "id": self.id,
            "label": self.label,
            "node_type": self.node_type,
            "payload": payload,
            "created_at": self.created_at,
            "data_classification": self.data_classification,
            "retention_policy": self.retention_policy,
            "redaction_mask": self.redaction_mask,
        }

    def compute_node_hash(self) -> str:
        """Return the canonical SHA-256 identity for this node."""

        canonical = json.dumps(
            self._canonical_payload(redact=False) | {"node_hash": ""},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def export_payload(self, *, redact: bool = False) -> dict[str, Any]:
        """Return a normalized node payload."""

        payload = self._canonical_payload(redact=redact)
        payload["node_hash"] = self.compute_node_hash()
        return payload


class EvidenceGraphEdge(BaseModel):
    """A directed edge connecting two evidence graph nodes."""

    source_id: str
    target_id: str
    relation: EdgeRelation
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_text)


class EvidenceGraph(BaseModel):
    """Traceable Evidence Graph container."""

    schema_version: str = "1.0"
    artifact_type: str = "reconforge-evidence-graph"
    graph_id: str
    workspace_id: str = "default"
    manifest_hash: str = ""
    nodes: dict[str, EvidenceGraphNode] = Field(default_factory=dict)
    edges: list[EvidenceGraphEdge] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_text)

    def add_node(self, node: EvidenceGraphNode) -> None:
        """Add a node to the graph and invalidate graph manifest hash."""

        self.nodes[node.id] = node

    def add_edge(
        self, source_id: str, target_id: str, relation: EdgeRelation, metadata: dict[str, Any] | None = None
    ) -> None:
        """Add a directed edge if both endpoints exist."""

        if source_id not in self.nodes:
            raise ValueError(f"Source node ID '{source_id}' not found in EvidenceGraph.")
        if target_id not in self.nodes:
            raise ValueError(f"Target node ID '{target_id}' not found in EvidenceGraph.")
        self.edges.append(
            EvidenceGraphEdge(
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                metadata=metadata or {},
            )
        )

    def _payload_nodes(self, *, redact: bool = False) -> dict[str, dict[str, Any]]:
        return {node_id: self.nodes[node_id].export_payload(redact=redact) for node_id in sorted(self.nodes)}

    def _payload_edges(self) -> list[dict[str, Any]]:
        return [
            {
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "relation": edge.relation,
                "metadata": edge.metadata,
                "created_at": edge.created_at,
            }
            for edge in sorted(
                self.edges,
                key=lambda candidate: (
                    candidate.source_id,
                    candidate.relation,
                    candidate.target_id,
                    candidate.created_at,
                    json.dumps(candidate.metadata, sort_keys=True, separators=(",", ":")),
                ),
            )
        ]

    def compute_manifest_hash(self) -> str:
        """Calculate a deterministic SHA-256 digest of the entire graph."""

        payload = json.dumps(
            {
                "artifact_type": self.artifact_type,
                "schema_version": self.schema_version,
                "graph_id": self.graph_id,
                "workspace_id": self.workspace_id,
                "created_at": self.created_at,
                "nodes": list(self._payload_nodes(redact=False).values()),
                "edges": self._payload_edges(),
            },
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=True,
        )
        self.manifest_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self.manifest_hash

    def verify_manifest_hash(self, manifest_hash: str) -> None:
        """Raise an error if a given manifest hash does not match current content."""

        actual = self.compute_manifest_hash()
        if actual != manifest_hash:
            raise ValueError(f"Manifest hash mismatch: expected {manifest_hash} but got {actual}")

    def to_payload(self, *, redact: bool = False) -> dict[str, Any]:
        """Return deterministic Graph payload including integrity metadata."""

        manifest = self.compute_manifest_hash()
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "workspace_id": self.workspace_id,
            "created_at": self.created_at,
            "nodes": self._payload_nodes(redact=redact),
            "edges": self._payload_edges(),
            "manifest_hash": manifest,
        }

    def trace_lineage(self, node_id: str) -> list[EvidenceGraphNode]:
        """Find all connected ancestor nodes for a given node ID."""

        if node_id not in self.nodes:
            raise KeyError(f"Node '{node_id}' does not exist in graph.")
        visited: set[str] = set()
        queue = [node_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            # Find outgoing edges where source_id == current
            for edge in self.edges:
                if edge.source_id == current and edge.target_id not in visited:
                    queue.append(edge.target_id)
        return [self.nodes[nid] for nid in sorted(visited) if nid in self.nodes]
