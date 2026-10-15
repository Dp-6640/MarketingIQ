"""Tool definitions in the shape the model sees.

Pydantic produces full JSON Schema; providers accept different subsets (Gemini rejects
`$ref`, `additionalProperties` and some formats). So each schema is inlined and reduced to
the portable core: type, properties, required, items, enum, description and numeric or
length bounds. Optional fields simply aren't required; defaults are stated in descriptions.
The input models still validate every call in full, so nothing is lost in safety.
"""

from typing import Any

from pydantic import BaseModel

from marketingiq.tools import TOOLS

_KEEP = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "description",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
}


def _portable(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in schema:
        return _portable(defs[schema["$ref"].split("/")[-1]], defs)
    if "anyOf" in schema:
        options = [o for o in schema["anyOf"] if o.get("type") != "null"]
        merged = {**_portable(options[0], defs)} if len(options) == 1 else {"type": "string"}
        if "description" in schema:
            merged["description"] = schema["description"]
        if "default" in schema and schema["default"] is not None:
            merged["description"] = (
                merged.get("description", "") + f" Default: {schema['default']}."
            ).strip()
        return merged
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "const":
            result["enum"] = [value]
        elif key == "properties":
            result[key] = {name: _portable(sub, defs) for name, sub in value.items()}
        elif key == "items":
            result[key] = _portable(value, defs)
        elif key in _KEEP:
            result[key] = value
    if schema.get("format") == "date":
        result["description"] = (result.get("description", "") + " Format YYYY-MM-DD.").strip()
    if "default" in schema and schema["default"] not in (None, [], {}):
        result["description"] = (
            result.get("description", "") + f" Default: {schema['default']}."
        ).strip()
    if result.get("type") == "object" and "properties" not in result:
        result["properties"] = {}
    return result


def portable_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    return _portable(schema, schema.get("$defs", {}))


def tool_definitions(extra: list[tuple[str, str, type[BaseModel]]] = ()) -> list[dict[str, Any]]:
    """Every registered tool, plus extra (name, description, model) entries."""
    entries = [(t.name, t.description, t.input_model) for t in TOOLS.values()] + list(extra)
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": portable_schema(model),
            },
        }
        for name, description, model in entries
    ]
