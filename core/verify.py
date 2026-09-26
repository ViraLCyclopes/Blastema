"""Compile a reconstruction in the running game.

The tool never claims a reconstruction works.  This is how you find out:
`CompilePrefab` must return a table.  nil means the prefab was rejected, and
nothing is logged about why - which is exactly why this check has to exist
rather than trusting output that merely looks right.
"""

from __future__ import annotations

import os
import random
import time

from core import probe

TEMPLATE = """return {{
    id = {request_id},
    run = function(out)
        local tbl = {body}
        local ok, res = pcall(api.entity.CompilePrefab, tbl, 'VLPR_{label}')
        out('VERIFY pcall=' .. tostring(ok) .. ' result=' ..
            ((ok and res ~= nil) and 'TABLE (compiles)' or 'nil (REJECTED)'))
    end
}}
"""


def extract_root(lua_text: str) -> str:
    """The table literal `GetRoot` returns."""
    after = lua_text.split("GetRoot = function()", 1)[1]
    body = after.split("return ", 1)[1]
    # cut at the `end` that closes GetRoot
    body = body.rsplit("\nend", 1)[0] if "\nend" in body else body
    body = body.strip()
    # vec3_const / vec2_const are not bound in the bridge's environment
    body = body.replace("vec3_const(", 'require("Vector3"):new(')
    body = body.replace("vec2_const(", 'require("Vector2"):new(')
    return body


def verify(path: str, label: str, timeout: float = 30.0) -> tuple[bool, str]:
    """Returns (compiles, message)."""
    with open(path, encoding="utf-8") as handle:
        body = extract_root(handle.read())
    request_id = random.randint(900000, 998000)
    with open(probe.REQUEST_FILE, "w", encoding="utf-8") as handle:
        handle.write(TEMPLATE.format(request_id=request_id, body=body,
                                     label=label[:24]))

    marker = "VLBRIDGE_RESP|%d|" % request_id
    before = os.path.getsize(probe.LOG_FILE) if os.path.exists(probe.LOG_FILE) else 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        if not os.path.exists(probe.LOG_FILE):
            continue
        with open(probe.LOG_FILE, encoding="utf-8", errors="replace") as handle:
            handle.seek(before)
            tail = handle.read()
        if marker in tail:
            line = tail.split(marker, 1)[1].split("\n", 1)[0]
            line = line.replace("ok|", "").strip()
            return ("TABLE" in line), line
    return False, "no response - is the game loaded into a world?"
