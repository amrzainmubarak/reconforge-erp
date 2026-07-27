"""Evidence Graph Schema and Lineage Verification Engine.

Transforms flat evidence binders into a traceable, queryable Evidence Graph
with strict node types, directed edge relationships, and SHA-256 integrity manifests.
"""

from __future__ import annotations

import hashlib
import json
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
    created_at: str = Field(default_factory=utc_now_text)
    node_hash: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.node_hash:
            canonical = json.dumps(
                {"id": self.id, "type": self.node_type, "payload": self.payload},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            object.__setattr__(self, "node_hash", hashlib.sha256(canonical.encode("utf-8")).hexdigest())


class EvidenceGraphEdge(BaseModel):
    """A directed edge connecting two evidence graph nodes."""

    source_id: str
    target_id: str
    relation: EdgeRelation
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_text)


class EvidenceGraph(BaseModel):
    """Traceable Evidence Graph container."""

    graph_id: str
    workspace_id: str = "default"
    nodes: dict[str, EvidenceGraphNode] = Field(default_factory=dict)
    edges: list[EvidenceGraphEdge] = Field(default_factory=list)
    manifest_hash: str = ""
    created_at: str = Field(default_factory=utc_now_text)

    def add_node(self, node: EvidenceGraphNode) -> None:
        """Add a node to the graph and invalidate graph manifest hash."""

        self.nodes[node.id] = node

    def add_edge(self, source_id: str, target_id: str, relation: EdgeRelation, metadata: dict[str, Any] | None = None) -> None:
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

    def compute_manifest_hash(self) -> str:
        """Calculate a deterministic SHA-256 digest of the entire graph."""

        canonical_nodes = [node.node_hash for node in sorted(self.nodes.values(), key=lambda n: n.id)]
        canonical_edges = [
            f"{e.source_id}->{e.relation}->{e.target_id}"
            for e in sorted(self.edges, key=lambda e: (e.source_id, e.relation, e.target_id))
        ]
        payload = json.dumps({"nodes": canonical_nodes, "edges": canonical_edges}, separators=(",", ":"))
        self.manifest_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self.manifest_hash

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
