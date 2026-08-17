# validation/mcq.py

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class MCQResolution:
    resolved: bool
    expected_label: Optional[str]
    expected_value: str
    options: Dict[str, str]
    method: str


class MultipleChoiceResolver:
    LABEL_RE = re.compile(r"^\s*([A-H])\s*$", re.IGNORECASE)
    LABELED_RE = re.compile(
        r"^\s*([A-H])\s*[\)\].:\-]\s*(.+?)\s*$",
        re.IGNORECASE | re.DOTALL,
    )

    # Accepte notamment :
    # A) 2, B) 4, C) 6, D) 8
    OPTION_RE = re.compile(
        r"(?is)(?:^|,\s*|[\n\r]+|\s{2,})"
        r"([A-H])\s*[\)\].:\-]\s*"
        r"(.*?)"
        r"(?=(?:,\s*|[\n\r]+|\s{2,})[A-H]\s*[\)\].:\-]\s*|$)"
    )

    def parse_options(self, options: Any) -> Dict[str, str]:
        if options is None:
            return {}

        if isinstance(options, dict):
            parsed = {}
            for key, value in options.items():
                label = str(key).strip().upper()
                if label in "ABCDEFGH" and value is not None:
                    parsed[label] = str(value).strip()
            return parsed

        if isinstance(options, list):
            parsed = {}
            for index, value in enumerate(options[:8]):
                if value is None:
                    continue

                label = chr(ord("A") + index)

                if isinstance(value, dict):
                    explicit_label = (
                        value.get("label")
                        or value.get("letter")
                        or value.get("key")
                    )
                    text_value = (
                        value.get("text")
                        or value.get("value")
                        or value.get("option")
                    )

                    if explicit_label and text_value is not None:
                        parsed[str(explicit_label).strip().upper()] = str(text_value).strip()
                    elif text_value is not None:
                        parsed[label] = str(text_value).strip()
                else:
                    parsed[label] = str(value).strip()

            return parsed

        text = str(options).strip()

        if not text:
            return {}

        try:
            decoded = json.loads(text)
            if decoded != options:
                parsed = self.parse_options(decoded)
                if parsed:
                    return parsed
        except Exception:
            pass

        parsed = {}

        for match in self.OPTION_RE.finditer(text):
            label = match.group(1).upper()
            value = match.group(2).strip()
            if value:
                parsed[label] = value

        return parsed

    def resolve_label(self, label: str, options: Any) -> Optional[str]:
        match = self.LABEL_RE.match((label or "").strip())
        if not match:
            return None

        parsed = self.parse_options(options)
        return parsed.get(match.group(1).upper())

    def resolve(
        self,
        question: str,
        expected_answer: str,
        options: Any = None,
    ) -> MCQResolution:
        expected = (expected_answer or "").strip()

        labeled_match = self.LABELED_RE.match(expected)
        if labeled_match:
            label = labeled_match.group(1).upper()
            value = labeled_match.group(2).strip()
            return MCQResolution(
                resolved=bool(value),
                expected_label=label,
                expected_value=value or expected,
                options={label: value} if value else {},
                method="expected_labeled_value",
            )

        label_match = self.LABEL_RE.match(expected)
        if not label_match:
            return MCQResolution(
                resolved=False,
                expected_label=None,
                expected_value=expected,
                options=self.parse_options(options),
                method="not_mcq_label",
            )

        expected_label = label_match.group(1).upper()
        parsed_options = self.parse_options(options)
        resolved_value = parsed_options.get(expected_label)

        if resolved_value:
            return MCQResolution(
                resolved=True,
                expected_label=expected_label,
                expected_value=resolved_value,
                options=parsed_options,
                method="mcq_database_options",
            )

        return MCQResolution(
            resolved=False,
            expected_label=expected_label,
            expected_value=expected,
            options=parsed_options,
            method="mcq_option_not_found",
        )
