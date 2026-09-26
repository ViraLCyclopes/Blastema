"""Write a reconstructed prefab as an ACSE `.lua`, in the shipped house style.

Formatting is not taste: hand-rolled layout is the loudest tell that a mod was
machine-written, and every shipped scenery mod uses one identical template.
The header block, the full local preamble, the `-- PropTool uses GetRoot ...`
comment (typo included, it is in every shipped file) and `GetFlattenedRoot` all
come from that template.
"""

from __future__ import annotations

TEMPLATE = """\
-----------------------------------------------------------------------
--/  @file    {name}.lua
--/  @author  {author}
--/  @version 1.0
--/
--/  @brief  Defines an ACSE prefab
--/
--/  @see    https://github.com/OpenNaja/ACSE
-----------------------------------------------------------------------
{provenance}
local global  = _G
local api     = global.api
local require = global.require
local pairs   = global.pairs
local ipairs  = global.ipairs

local {name} = module(...)

-- PropTool uses GetRoot to build the inject the prefabs in ACSE
{name}.GetRoot = function()
    -- Your prefab information goes in here
    return {body}
end

-- Relay on the current entity API to generate the complete prefab
{name}.GetFlattenedRoot = function()
    local tPrefab = api.entity.CompilePrefab( {name}.GetRoot(), '{name}')
    return api.entity.FindPrefab('{name}')
end

return {name}
"""

PROVENANCE = """\
-- Reconstructed from the running game, not hand-authored.  JWE3 does not expose
-- this prefab to Lua ({name} is referenced {refs} times in the prefab dump but
-- never defined there, and api.entity.FindPrefab returns nil for it), so a Lua
-- prefab cannot inherit it: doing so compiles and spawns an entity missing
-- everything the base provided.
--
-- Source: the FLATTENED `{consumer}` / `{child}` read out of a live session,
-- which is that base's real content.  Local overrides the consumer applies were
-- subtracted; see PrefabReconstructor.
"""


def strip_overrides(body: str, override_keys: list[str]) -> str:
    """Drop top-level keys the consumer set itself, so only the base remains.

    Conservative on purpose: only exact top-level keys are removed, because a
    wrong subtraction produces a prefab that looks plausible and is missing
    something the base actually supplied.
    """
    if not override_keys:
        return body
    lines = body.splitlines(keepends=True)
    out: list[str] = []
    skip_until_indent: int | None = None
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if skip_until_indent is not None:
            if indent <= skip_until_indent and stripped.startswith("}"):
                skip_until_indent = None
            continue
        key = stripped.split(" = ", 1)[0] if " = " in stripped else None
        if key in override_keys and stripped.rstrip().endswith("{"):
            skip_until_indent = indent
            continue
        out.append(line)
    return "".join(out)


def render(name: str, body: str, consumer: str, child: str, refs: int,
           author: str = "reconstructed") -> str:
    provenance = PROVENANCE.format(name=name, refs=refs, consumer=consumer,
                                   child=child)
    indented = "\n".join(
        ("    " + line) if line.strip() else line for line in body.splitlines()
    ).lstrip()
    return TEMPLATE.format(name=name, body=indented, author=author,
                           provenance=provenance)
