"""Export the FastAPI OpenAPI document with deterministic JSON formatting."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def parse_args() -> argparse.Namespace:
    """Parse the required destination for a schema export."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="Path for the exported OpenAPI JSON document")
    return parser.parse_args()


def sort_json_value(value: JsonValue) -> JsonValue:
    """Return an equivalent JSON value with every object key in sorted order."""
    match value:
        case dict():
            return {key: sort_json_value(nested_value) for key, nested_value in sorted(value.items())}
        case list():
            return [sort_json_value(nested_value) for nested_value in value]
        case _:
            return value


def main() -> None:
    """Import the application and write its canonical OpenAPI document."""
    output_path = parse_args().output
    repository_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository_root / "backend"))

    from app.main import app

    schema = sort_json_value(app.openapi())
    output_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
