from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from services.naima.semantic_compiler_service import (
    compile_parameterization,
)
from services.naima.semantic_schema import (
    SemanticConstraint,
    SemanticSituation,
    normalize_semantic_payload,
)


JsonInterpreter = Callable[[str], Dict[str, Any]]


SEMANTIC_INTERPRETER_SYSTEM_PROMPT = """
Tu es un interprète sémantique mathématique.

Ton rôle n'est PAS de dire si l'élève a raison ou tort.
Ton rôle n'est PAS de résoudre l'exercice pour l'élève.

Tu dois uniquement convertir un énoncé mathématique verbal
en une représentation structurée indépendante du domaine.

Retourne exclusivement un objet JSON.

Relations autorisées :
- equality
- sum_equals
- difference_equals
- multiple_of
- product_offset_common_value

Pour product_offset_common_value, utilise :
{
  "relation": "product_offset_common_value",
  "data": {
    "quantity": nombre,
    "offset": nombre_signe,
    "item": "nom de l'objet si connu",
    "unit_role": "unit_value",
    "common_role": "available_amount"
  }
}

Convention :
common_value = quantity * unit_value + offset

Donc :
- "il me manque 5" => offset = -5
- "il me reste 12" => offset = +12

Le JSON doit respecter ce format :
{
  "status": "interpreted" | "uncertain",
  "confidence": 0.0,
  "entities": [
    {
      "role": "...",
      "label": "...",
      "symbol": null,
      "entity_type": "quantity"
    }
  ],
  "constraints": [
    {
      "relation": "...",
      "data": {},
      "source_text": "...",
      "confidence": 0.0
    }
  ],
  "target_role": "...",
  "parameterizations": [],
  "ambiguities": []
}

N'invente jamais une donnée absente.
Si une relation est ambiguë, indique-la dans "ambiguities".
"""


def _legacy_constraints_to_semantic(
    constraints: Optional[List[Dict[str, Any]]],
) -> List[SemanticConstraint]:

    output: List[SemanticConstraint] = []

    for item in constraints or []:
        if not isinstance(item, dict):
            continue

        relation = str(
            item.get("relation")
            or ""
        ).strip()

        if not relation:
            continue

        if relation == "product_offset_common_value":

            output.append(
                SemanticConstraint(
                    relation=relation,
                    data={
                        "quantity": item.get("quantity"),
                        "offset": item.get("offset"),
                        "offset_kind": item.get("offset_kind"),
                        "item": item.get("item"),
                        "unit_role": (
                            item.get("unit_role")
                            or "unit_value"
                        ),
                        "common_role": (
                            item.get("common_role")
                            or "available_amount"
                        ),
                    },
                    source_text=item.get("source_text"),
                    confidence=1.0,
                )
            )

        else:
            output.append(
                SemanticConstraint(
                    relation=relation,
                    data=dict(item),
                    confidence=1.0,
                )
            )

    return output


def _merge_constraints(
    deterministic: List[SemanticConstraint],
    interpreted: List[SemanticConstraint],
) -> List[SemanticConstraint]:

    merged: List[SemanticConstraint] = []
    signatures = set()

    def signature(
        constraint: SemanticConstraint,
    ):
        data = dict(constraint.data or {})

        return (
            constraint.relation,
            str(data.get("quantity")),
            str(data.get("offset")),
            str(data.get("item")).lower(),
            str(data.get("common_role")).lower(),
        )

    for constraint in deterministic:
        sig = signature(constraint)
        signatures.add(sig)
        merged.append(constraint)

    for constraint in interpreted:
        sig = signature(constraint)

        if sig in signatures:
            continue

        signatures.add(sig)
        merged.append(constraint)

    return merged


def call_openai_semantic_interpreter(
    statement: str,
    *,
    model: Optional[str] = None,
) -> Dict[str, Any]:

    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(
            "Le package openai n'est pas disponible."
        ) from exc

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY")
    )

    selected_model = (
        model
        or os.getenv("NAIMA_SEMANTIC_MODEL")
        or "gpt-4o-mini"
    )

    response = client.chat.completions.create(
        model=selected_model,
        temperature=0,
        response_format={
            "type": "json_object",
        },
        messages=[
            {
                "role": "system",
                "content": SEMANTIC_INTERPRETER_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "Énoncé à interpréter :\n"
                    + str(statement or "")
                ),
            },
        ],
    )

    content = (
        response.choices[0].message.content
        or "{}"
    )

    return json.loads(content)


def interpret_math_situation(
    *,
    statement: str,
    deterministic_constraints: Optional[
        List[Dict[str, Any]]
    ] = None,
    llm_interpreter: Optional[
        JsonInterpreter
    ] = None,
    use_llm_fallback: bool = True,
) -> SemanticSituation:

    statement = str(
        statement
        or ""
    ).strip()

    deterministic = _legacy_constraints_to_semantic(
        deterministic_constraints
    )

    enough_deterministic_structure = bool(
        len(deterministic) >= 2
    )

    interpreted_situation = SemanticSituation(
        status=(
            "interpreted"
            if enough_deterministic_structure
            else "uncertain"
        ),
        statement=statement,
        constraints=list(deterministic),
        confidence=(
            1.0
            if enough_deterministic_structure
            else 0.0
        ),
        source="deterministic",
    )

    if (
        enough_deterministic_structure
        or not use_llm_fallback
    ):
        return interpreted_situation

    interpreter = (
        llm_interpreter
        or call_openai_semantic_interpreter
    )

    try:
        payload = interpreter(statement)

        llm_situation = normalize_semantic_payload(
            payload,
            statement=statement,
            source="llm",
        )

    except Exception as exc:
        interpreted_situation.ambiguities.append(
            "semantic_llm_unavailable:"
            + type(exc).__name__
        )
        return interpreted_situation

    merged_constraints = _merge_constraints(
        deterministic,
        llm_situation.constraints,
    )

    source = (
        "hybrid"
        if deterministic
        else "llm"
    )

    return SemanticSituation(
        status=(
            "interpreted"
            if merged_constraints
            else "uncertain"
        ),
        statement=statement,
        entities=list(llm_situation.entities),
        constraints=merged_constraints,
        target_role=llm_situation.target_role,
        parameterizations=list(
            llm_situation.parameterizations
        ),
        ambiguities=list(llm_situation.ambiguities),
        confidence=min(
            1.0,
            max(
                llm_situation.confidence,
                1.0 if deterministic else 0.0,
            ),
        ),
        source=source,
        raw_interpretation=dict(
            llm_situation.raw_interpretation
        ),
    )


def infer_role_from_variable_meaning(
    *,
    meaning: str,
    situation: SemanticSituation,
) -> Optional[str]:

    normalized = str(
        meaning
        or ""
    ).strip().lower()

    if not normalized:
        return None

    for entity in situation.entities:
        label = str(
            entity.label
            or ""
        ).strip().lower()

        if (
            label
            and (
                label in normalized
                or normalized in label
            )
        ):
            return entity.role

    roles = set()

    for constraint in situation.constraints:
        data = dict(constraint.data or {})

        for key in (
            "unit_role",
            "common_role",
            "subject_role",
            "reference_role",
        ):
            role = data.get(key)
            if role:
                roles.add(str(role))

    if len(roles) == 1:
        return next(iter(roles))

    return None


def reparameterize_situation(
    *,
    situation: SemanticSituation,
    variable: str,
    role: str,
    meaning: str,
) -> Dict[str, Any]:

    parameterization = compile_parameterization(
        situation=situation,
        variable=variable,
        role=role,
        meaning=meaning,
    )

    return {
        "status": (
            "compiled"
            if parameterization.equations
            else "uncertain"
        ),
        "variable": variable,
        "role": role,
        "meaning": meaning,
        "equations": list(
            parameterization.equations
        ),
        "compiled_deterministically": True,
    }
