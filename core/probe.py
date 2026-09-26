"""Read a prefab out of the running game through VLBridge.

`api.entity.FindPrefab` returns the FULLY FLATTENED prefab - inherited
components, resolved bindings, values and all - which is the only place an
engine-side base's real content can be read.  The dump records a child as
`Prefab = '<name>'` plus overrides and nothing more.

Transport is the documented direct route: write `Dev/Lua/vlbridge_req.lua`
with our own id, then tail the game log for `VLBRIDGE_RESP|<id>|`.  That
sidesteps the MCP payload limit, which a whole prefab subtree can exceed.
"""

from __future__ import annotations

import os
import re
import time

GAME_ROOT = os.path.join(
    "C:\\", "Program Files (x86)", "Steam", "steamapps", "common",
    "Jurassic World Evolution 3",
)
REQUEST_FILE = os.path.join(GAME_ROOT, "Dev", "Lua", "vlbridge_req.lua")
LOG_FILE = os.path.join(GAME_ROOT, "Jurassic World Evolution 3.log")

# Serialises a prefab subtree as Lua source.  Kept as one string so the probe
# stays a single request; the game is the scarce resource here, not bandwidth.
SERIALISER = r"""
local function isvec(v)
    local s = tostring(v)
    return s:sub(1, 1) == "(" and s:find(",") ~= nil
end
local function vecargs(v)
    local s = tostring(v):gsub("[()]", "")
    return s
end
local function keyok(k)
    return type(k) == "string" and k:match("^[A-Za-z_][A-Za-z_0-9]*$") ~= nil
end
local ser
ser = function(v, indent, out)
    local t = type(v)
    if t == "string" then
        out[#out+1] = "'" .. v .. "'"
    elseif t == "number" or t == "boolean" then
        out[#out+1] = tostring(v)
    elseif t == "userdata" then
        if isvec(v) then
            local a = select(2, pcall(vecargs, v))
            local n = select(2, string.gsub(tostring(v), ",", ","))
            out[#out+1] = (n == 1 and "vec2_const(" or "vec3_const(") .. a .. ")"
        else
            out[#out+1] = "'<userdata>'"
        end
    elseif t == "table" then
        if v.__property ~= nil then
            out[#out+1] = "{ __property = '" .. tostring(v.__property) .. "' }"
            return
        end
        local keys, arr = {}, {}
        for k, _ in pairs(v) do
            if type(k) == "number" then arr[#arr+1] = k else keys[#keys+1] = k end
        end
        table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
        table.sort(arr)
        if #keys == 0 and #arr == 0 then out[#out+1] = "{}" return end
        out[#out+1] = "{\n"
        local pad = string.rep("    ", indent + 1)
        for _, k in ipairs(arr) do
            out[#out+1] = pad
            ser(v[k], indent + 1, out)
            out[#out+1] = ",\n"
        end
        for _, k in ipairs(keys) do
            out[#out+1] = pad .. (keyok(k) and k or ("['" .. tostring(k) .. "']")) .. " = "
            ser(v[k], indent + 1, out)
            out[#out+1] = ",\n"
        end
        out[#out+1] = string.rep("    ", indent) .. "}"
    else
        out[#out+1] = "nil"
    end
end
"""


INTERSECT = r"""
-- Keep only what EVERY consumer agrees on.  A key that differs between two
-- consumers is that consumer's own override (a position, a network element);
-- a key they all share with the same value came from the base.  This is why
-- several consumers are read instead of trying to subtract the dump's
-- overrides textually - the dump records overrides nested inside Components,
-- so a naive top-level subtraction deletes the very content being recovered.
local function same(a, b)
    if type(a) ~= type(b) then return false end
    if type(a) == "userdata" then return tostring(a) == tostring(b) end
    if type(a) == "table" then return true end
    return a == b
end
local function intersect(nodes)
    local first = nodes[1]
    if type(first) ~= "table" then
        for i = 2, #nodes do
            if not same(first, nodes[i]) then return nil, true end
        end
        return first, false
    end
    local out, dropped = {}, false
    for k, v in pairs(first) do
        local all, vals = true, { v }
        for i = 2, #nodes do
            local other = nodes[i]
            if type(other) ~= "table" or other[k] == nil then all = false break end
            vals[#vals+1] = other[k]
        end
        if all then
            local merged, lost = intersect(vals)
            if merged ~= nil then out[k] = merged end
            dropped = dropped or lost
        else
            dropped = true
        end
    end
    return out, dropped
end
"""


def build_intersect_request(request_id: int, sources: list[tuple[str, str]]) -> str:
    """Read several consumers and serialise only what they all share."""
    lookups = "\n".join(
        "        do local p = api.entity.FindPrefab('%s')\n"
        "           local n = p and p.Children and p.Children['%s']\n"
        "           if n == nil then out('ERR missing %s/%s') return end\n"
        "           nodes[#nodes+1] = n end" % (entry, child, entry, child)
        for entry, child in sources
    )
    return (
        "return {\n"
        "    id = %d,\n"
        "    run = function(out)\n"
        "%s\n%s\n"
        "        local nodes = {}\n"
        "%s\n"
        "        local merged, dropped = intersect(nodes)\n"
        "        out('SOURCES %d DROPPED ' .. tostring(dropped))\n"
        "        local buf = {}\n"
        "        ser(merged, 0, buf)\n"
        "        local s = table.concat(buf)\n"
        "        for i = 1, #s, 900 do out('CHUNK' .. s:sub(i, i + 899)) end\n"
        "        out('ENDCHUNK')\n"
        "    end\n"
        "}\n" % (request_id, SERIALISER, INTERSECT, lookups, len(sources))
    )


def build_request(request_id: int, entry: str, child: str | None) -> str:
    """Lua that serialises either a whole prefab or one of its children."""
    if child:
        target = ("local p = api.entity.FindPrefab('%s')\n"
                  "        local node = p and p.Children and p.Children['%s']" % (entry, child))
    else:
        target = "local node = api.entity.FindPrefab('%s')" % entry
    return (
        "return {\n"
        "    id = %d,\n"
        "    run = function(out)\n"
        "%s\n"
        "        %s\n"
        "        if node == nil then out('ERR node not found') return end\n"
        "        local buf = {}\n"
        "        ser(node, 0, buf)\n"
        "        local s = table.concat(buf)\n"
        "        for i = 1, #s, 900 do out('CHUNK' .. s:sub(i, i + 899)) end\n"
        "        out('ENDCHUNK')\n"
        "    end\n"
        "}\n" % (request_id, SERIALISER, target)
    )


def run(request_id: int, entry: str, child: str | None = None,
        timeout: float = 30.0, sources: list[tuple[str, str]] | None = None) -> str:
    """Send the probe and return the serialised Lua, or raise.

    With `sources` (several consumers) the game returns only what they all
    agree on, which is the base's own content.
    """
    marker = "VLBRIDGE_RESP|%d|" % request_id
    before = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0
    body_lua = (build_intersect_request(request_id, sources) if sources
                else build_request(request_id, entry, child))
    with open(REQUEST_FILE, "w", encoding="utf-8") as handle:
        handle.write(body_lua)

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        if not os.path.exists(LOG_FILE):
            continue
        with open(LOG_FILE, encoding="utf-8", errors="replace") as handle:
            handle.seek(before)
            tail = handle.read()
        if marker in tail:
            body = tail.split(marker, 1)[1].split("\n", 1)[0]
            if body.startswith("ok|"):
                body = body[3:]
            if "ERR " in body:
                raise RuntimeError(body.strip())
            parts = re.findall(r"CHUNK(.*?)(?=CHUNK|ENDCHUNK|$)", body, re.S)
            text = "".join(parts).replace("\\n", "\n").replace("\\t", "\t")
            if not text.strip():
                raise RuntimeError("probe returned nothing: " + body[:200])
            return text
    raise TimeoutError(
        "no response for id %d in %.0fs - is the game running and in a world?"
        % (request_id, timeout)
    )
