from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SemanticEntity:
    role: str
    label: str
    symbol: Optional[str] = None
    entity_type: str = "quantity"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticConstraint:
    relation: str
    data: Dict[str, Any] = field(default_factory=dict)
    source_text: Optional[str] = None
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticParameterization:
    variable: str
    role: str
    meaning: str
    equations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticSituation:
    status: str = "uninterpreted"
    statement: str = ""
    entities: List[SemanticEntity] = field(default_factory=list)
    constraints: List[SemanticConstraint] = field(default_factory=list)
    target_role: Optional[str] = None
    parameterizations: List[SemanticParameterization] = field(default_factory=list)
    ambiguities: List[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "unknown"
    raw_interpretation: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "statement": self.statement,
            "entities": [item.to_dict() for item in self.entities],
            "constraints": [item.to_dict() for item in self.constraints],
            "target_role": self.target_role,
            "parameterizations": [
                item.to_dict()
                for item in self.parameterizations
            ],
            "ambiguities": list(self.ambiguities),
            "confidence": float(self.confidence),
            "source": self.source,
            "raw_interpretation": dict(self.raw_interpretation),
        }


ALLOWED_RELATIONS = {
    "equality",
    "sum_equals",
    "difference_equals",
    "multiple_of",
    "product_offset_common_value",
}


def normalize_semantic_payload(
    payload: Dict[str, Any],
    *,
    statement: str = "",
    source: str = "llm",
) -> SemanticSituation:

    payload = dict(payload or {})

    entities: List[SemanticEntity] = []
    for item in payload.get("entities", []) or []:
        if not isinstance(item, dict):
            continue

        role = str(item.get("role") or "").strip()
        label = str(item.get("label") or "").strip()

        if not role or not label:
            continue

        entities.append(
            SemanticEntity(
                role=role,
                label=label,
                symbol=(
                    str(item.get("symbol")).strip()
                    if item.get("symbol")
                    else None
                ),
                entity_type=str(
                    item.get("entity_type")
                    or "quantity"
                ),
                metadata=dict(item.get("metadata") or {}),
            )
        )

    constraints: List[SemanticConstraint] = []
    for item in payload.get("constraints", []) or []:
        if not isinstance(item, dict):
            continue

        relation = str(item.get("relation") or "").strip()

        if relation not in ALLOWED_RELATIONS:
            continue

        constraints.append(
            SemanticConstraint(
                relation=relation,
                data=dict(item.get("data") or {}),
                source_text=(
                    str(item.get("source_text")).strip()
                    if item.get("source_text")
                    else None
                ),
                confidence=float(
                    item.get("confidence", 1.0)
                    or 0.0
                ),
            )
        )

    parameterizations: List[SemanticParameterization] = []
    for item in payload.get("parameterizations", []) or []:
        if not isinstance(item, dict):
            continue

        variable = str(item.get("variable") or "").strip()
        role = str(item.get("role") or "").strip()
        meaning = str(item.get("meaning") or "").strip()

        if not variable or not role:
            continue

        parameterizations.append(
            SemanticParameterization(
                variable=variable,
                role=role,
                meaning=meaning,
                equations=[
                    str(eq).strip()
                    for eq in (item.get("equations") or [])
                    if str(eq).strip()
                ],
                metadata=dict(item.get("metadata") or {}),
            )
        )

    ambiguities = [
        str(value).strip()
        for value in (payload.get("ambiguities") or [])
        if str(value).strip()
    ]

    target_role = (
        str(payload.get("target_role")).strip()
        if payload.get("target_role")
        else None
    )

    confidence = float(
        payload.get("confidence", 0.0)
        or 0.0
    )

    status = str(
        payload.get("status")
        or ("interpreted" if constraints else "uncertain")
    )

    return SemanticSituation(
        status=status,
        statement=str(
            statement
            or payload.get("statement")
            or ""
        ).strip(),
        entities=entities,
        constraints=constraints,
        target_role=target_role,
        parameterizations=parameterizations,
        ambiguities=ambiguities,
        confidence=max(0.0, min(1.0, confidence)),
        source=source,
        raw_interpretation=payload,
    )
