"""JWE3 component schemas (.specdef) and enum value sets (.enumnamer).

Both ship inside `GameMain/Main.ovl`; extract them with cobra-tools once and
point SPECDEF_DIR at the result.  They give three things the prefab dump cannot:

* which fields a component actually has, and whether each is optional - so a
  reconstruction can be checked for invented or missing fields;
* the declared type of a field, which is what a Property override needs under
  rule 7 (a property the parent does not declare MUST specify `Type`);
* the valid members of an enum, which is what catches a ROTTED enum name
  before the game does.  A name the namer does not know takes the whole prefab
  down with it and nothing is logged.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

# Configured in core.settings; both ship inside GameMain/Main.ovl and the kit
# keeps an extracted copy of each.
def _dirs() -> tuple[str, str]:
    from core.settings import SETTINGS
    return (SETTINGS.specdef_dir or "", SETTINGS.enumnamer_dir or "")


SPECDEF_DIR = None
ENUMNAMER_DIR = None

# SpecdefDtype -> the string a prefab Property's `Type` field wants.
DTYPE_TO_PROPERTY_TYPE = {
    "STRING": "string",
    "FLOAT": "float",
    "BOOL": "bool",
    "U_INT_32": "uint32",
    "U_INT_64": "uint64",
    "INT_32": "int32",
    "VECTOR2": "vector2",
    "VECTOR3": "vector3",
    "REFERENCE_TO_OBJECT": "entity",
}


class Field:
    __slots__ = ("name", "dtype", "optional", "default")

    def __init__(self, name: str, dtype: str, optional: bool, default: str | None):
        self.name, self.dtype = name, dtype
        self.optional, self.default = optional, default

    @property
    def property_type(self) -> str | None:
        return DTYPE_TO_PROPERTY_TYPE.get(self.dtype)

    def __repr__(self) -> str:
        return "Field(%s, %s, optional=%s)" % (self.name, self.dtype, self.optional)


class Schema:
    def __init__(self, directory: str | None = None,
                 enum_directory: str | None = None):
        detected = _dirs()
        self.directory = directory or detected[0]
        self.enum_directory = enum_directory or detected[1]
        self._specdefs: dict[str, list[Field]] = {}
        self._enums: dict[str, set[str]] = {}

    # -- components ------------------------------------------------------
    def component(self, name: str) -> list[Field] | None:
        """Fields of a component, by its prefab name (case-insensitive)."""
        key = name.lower()
        if key in self._specdefs:
            return self._specdefs[key]
        path = os.path.join(self.directory, key + ".specdef")
        if not os.path.exists(path):
            return None
        fields: list[Field] = []
        root = ET.parse(path).getroot()
        for spec in root.iter("spec"):
            dtype = (spec.get("dtype") or "").replace("SpecdefDtype.", "")
            name_node = spec.find("name_ptr")
            data = spec.find("data_ptr/dtype")
            if name_node is None:
                continue
            fields.append(Field(
                (name_node.text or "").strip(), dtype,
                (data is not None and data.get("ioptional") == "1"),
                (data.get("ivalue") if data is not None else None),
            ))
        self._specdefs[key] = fields
        return fields

    def unknown_fields(self, component: str, used: list[str]) -> list[str]:
        """Fields we emit that the component does not declare."""
        fields = self.component(component)
        if fields is None:
            return []
        known = {f.name.lower() for f in fields}
        return [u for u in used if u.lower() not in known]

    # -- enums -----------------------------------------------------------
    def enum(self, name: str) -> set[str] | None:
        key = name.lower()
        if key in self._enums:
            return self._enums[key]
        path = os.path.join(self.enum_directory, key + ".enumnamer")
        if not os.path.exists(path):
            return None
        text = open(path, encoding="utf-8", errors="replace").read()
        values = set(re.findall(r"<pointer[^>]*>([^<]+)</pointer>", text))
        self._enums[key] = values
        return values

    def invalid_enum_values(self, enum_name: str, used: list[str]) -> list[str]:
        """Values that the namer does not know - each one is fatal."""
        values = self.enum(enum_name)
        if values is None:
            return []
        return [u for u in used if u not in values]

    def available(self) -> tuple[int, int]:
        specs = len([f for f in os.listdir(self.directory) if f.endswith(".specdef")])
        enums = len([f for f in os.listdir(self.enum_directory)
                     if f.endswith(".enumnamer")])
        return specs, enums
