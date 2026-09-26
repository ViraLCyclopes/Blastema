"""Read the JWE3 prefab dump.

The dump is not loadable Lua, so everything here is textual.  Two facts drive
the whole tool:

* a top-level entry is the only place a prefab is DEFINED, and the dump
  normalises those keys to lowercase (13,716 lowercase vs 8 mixed-case), so
  every lookup is case-insensitive;
* a child that inherits something records only `Prefab = '<name>'` plus its own
  local overrides.  The base's actual content is NOT in the dump - that has to
  come from the running game.
"""

from __future__ import annotations

import os
import re
from collections import Counter

ENTRY_RE = re.compile(r"^([A-Za-z_0-9]+) = \{", re.M)
PREFAB_REF_RE = re.compile(r"Prefab = '([^']+)'")


class Dump:
    def __init__(self, path: str):
        self.path = path
        with open(path, encoding="utf-8", errors="replace") as handle:
            self.text = handle.read()
        self._entries = {m.group(1).lower(): m.start() for m in ENTRY_RE.finditer(self.text)}

    # -- entries ---------------------------------------------------------
    def defines(self, name: str) -> bool:
        """Is this prefab DEFINED at column 0?  Case-insensitive by design."""
        return name.lower() in self._entries

    def entry_names(self) -> list[str]:
        return sorted(self._entries)

    def block(self, name: str) -> str | None:
        """The full `name = { ... }` text, brace-matched."""
        start = self._entries.get(name.lower())
        if start is None:
            return None
        open_brace = self.text.index("{", start)
        depth = 0
        for index in range(open_brace, len(self.text)):
            char = self.text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return self.text[start:index + 1]
        return None

    # -- references ------------------------------------------------------
    def reference_counts(self) -> Counter:
        return Counter(PREFAB_REF_RE.findall(self.text))

    def engine_side_candidates(self) -> list[tuple[str, int]]:
        """Referenced as a parent but never defined.  Confirm each in game."""
        counts = self.reference_counts()
        missing = [(n, c) for n, c in counts.items() if not self.defines(n)]
        return sorted(missing, key=lambda pair: (-pair[1], pair[0]))

    def consumers(self, base: str) -> list[tuple[str, str | None, int]]:
        """Everything that inherits `base`, as a child OR at its own root.

        Returns (entry, child_name_or_None, override_size) sorted by SMALLEST
        override, because the fewer local overrides a consumer applies, the
        closer its flattened form is to the base itself.

        Root inheritors matter: a base only ever used as a root parent - like
        FoodBaseSingleGoalpoint, which `foodbasesinglemodel` roots on - has no
        child anywhere, and searching only children finds nothing at all.  For
        those, FindPrefab on the inheritor itself returns the flattened base.
        """
        needle = "Prefab = '%s'" % base
        found: list[tuple[str, str | None, int]] = []
        for entry in self._entries:
            block = self.block(entry)
            if block is None or needle not in block:
                continue
            for child, body in self._children_using(block, needle):
                found.append((entry, child, len(body)))
            # root-level: `Prefab = '<base>'` at one tab, i.e. on the entry itself
            if re.search(r"^\t%s,?$" % re.escape(needle), block, re.M):
                found.append((entry, None, len(block)))
        return sorted(found, key=lambda row: row[2])

    @staticmethod
    def _children_using(block: str, needle: str) -> list[tuple[str, str]]:
        """(child name, child body) for every child whose table holds `needle`."""
        out: list[tuple[str, str]] = []
        for match in re.finditer(r"^(\t+)([A-Za-z_0-9]+) = \{$", block, re.M):
            indent, name = match.group(1), match.group(2)
            start = match.end()
            depth = 1
            index = start
            while index < len(block) and depth > 0:
                if block[index] == "{":
                    depth += 1
                elif block[index] == "}":
                    depth -= 1
                index += 1
            body = block[start:index]
            # only the child that DIRECTLY roots on it, not a nested descendant
            direct = re.search(
                r"^\t{%d}%s,?$" % (len(indent) + 1, re.escape(needle)), body, re.M
            )
            if direct:
                out.append((name, body))
        return out


def default_dump_path() -> str:
    """The dump in the game root, newest version first."""
    root = os.path.join(
        "C:\\", "Program Files (x86)", "Steam", "steamapps", "common",
        "Jurassic World Evolution 3",
    )
    candidates = sorted(
        (f for f in os.listdir(root) if f.startswith("JWE3_") and f.endswith("_Prefabs.lua")),
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("no JWE3_*_Prefabs.lua in the game root")
    return os.path.join(root, candidates[0])
