"""Reconstruct a JWE3 engine-side prefab as a Lua one.

    python reconstruct.py census
    python reconstruct.py plan  BLDG_PathJoinPoint
    python reconstruct.py build BLDG_PathJoinPoint

`census` and `plan` are offline.  `build` needs the game running and loaded
into a world, because the base's real content can only be read from a
FLATTENED prefab in a live session - the dump records inheritors as
`Prefab = '<name>'` plus their own overrides and nothing more.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import emit, probe  # noqa: E402
from core.dump import Dump, default_dump_path  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def cmd_census(dump: Dump, args) -> int:
    rows = dump.engine_side_candidates()
    print("referenced as a parent but never defined: %d" % len(rows))
    print("(confirm each in game - FindPrefab must return nil)\n")
    shown = [r for r in rows if r[1] >= args.min_refs]
    for name, count in shown:
        print("  %5d  %s" % (count, name))
    print("\nshown: %d with >= %d references" % (len(shown), args.min_refs))
    return 0


def cmd_plan(dump: Dump, args) -> int:
    base = args.name
    if dump.defines(base):
        print("%s IS defined in the dump - inherit it directly, do not "
              "reconstruct it." % base)
        return 1
    refs = dump.reference_counts()[base]
    rows = dump.consumers(base)
    print("%s: %d references, %d consumers" % (base, refs, len(rows)))
    if not rows:
        print("no consumer found; nothing to read the content from.")
        return 1
    print("\nbest sources (smallest local override wins):")
    for entry, child, size in rows[:8]:
        print("  %-46s %-30s override=%dB" % (
            entry, ("child=" + child) if child else "(root inheritor)", size))
    picked = rows[:3]
    print("\nwould intersect these %d, keeping only what they all agree on:" % len(picked))
    for entry, child, _ in picked:
        print("   FindPrefab('%s')%s" % (
            entry, (".Children['%s']" % child) if child else "   (root inheritor)"))
    print("\nA key two consumers disagree on is that consumer's own override;")
    print("a key they all share came from the base.")
    return 0


def _override_keys(dump: Dump, entry: str, child: str) -> list[str]:
    """Top-level keys the consumer sets on the child itself."""
    block = dump.block(entry) or ""
    match = re.search(r"^(\t+)%s = \{$" % re.escape(child), block, re.M)
    if not match:
        return []
    indent = len(match.group(1)) + 1
    start = match.end()
    depth, index = 1, start
    while index < len(block) and depth > 0:
        if block[index] == "{":
            depth += 1
        elif block[index] == "}":
            depth -= 1
        index += 1
    body = block[start:index]
    keys = re.findall(r"^\t{%d}([A-Za-z_0-9]+) = " % indent, body, re.M)
    return [k for k in keys if k != "Prefab"]



def _schema_warnings(body: str) -> list[tuple[str, list[str]]]:
    """Fields we emit that the component's specdef does not declare.

    A warning, not a failure: a specdef may be missing for a component, and a
    reconstruction that is merely unusual is still worth looking at by hand.
    """
    try:
        from core.schema import Schema
    except Exception:
        return []
    schema = Schema()
    out: list[tuple[str, list[str]]] = []
    for match in re.finditer(r"^(\s+)([A-Za-z_0-9]+) = \{$", body, re.M):
        component = match.group(2)
        if schema.component(component) is None:
            continue
        indent = len(match.group(1))
        # only this component's own block: stop at its closing brace, or the
        # fields of the NEXT component get blamed on this one
        rest = body[match.end():]
        end = re.search(r"^\s{%d}\}" % indent, rest, re.M)
        own = rest[:end.start()] if end else rest
        fields = re.findall(r"^\s{%d}([A-Za-z_0-9]+) = " % (indent + 4), own, re.M)
        unknown = schema.unknown_fields(component, fields)
        if unknown:
            out.append((component, unknown))
    return out


def cmd_build(dump: Dump, args) -> int:
    base = args.name
    if dump.defines(base):
        print("%s is defined in the dump; inherit it instead." % base)
        return 1
    rows = dump.consumers(base)
    if not rows:
        print("no consumer to read %s from." % base)
        return 1
    sources = [(entry, child) for entry, child, _ in rows[:args.sources]]
    print("reading %d consumers and keeping only what they agree on:" % len(sources))
    for entry, child in sources:
        print("   %s%s" % (entry, (" / " + child) if child else "   (root inheritor)"))
    request_id = random.randint(900000, 998000)
    body = probe.run(request_id, None, None, sources=sources)
    header, _, body = body.partition("\n") if body.startswith("SOURCES") else ("", "", body)
    if header:
        print("   %s" % header.strip())

    entry, child = sources[0]
    text = emit.render(base, body, entry, child, dump.reference_counts()[base])
    problems = emit.check_wellformed(text)
    if problems:
        print("REFUSING to write - the reconstruction is malformed:")
        for problem in problems:
            print("   %s" % problem)
        return 1
    for component, unknown in _schema_warnings(body):
        print("   WARNING %s declares no field(s): %s" % (component, unknown))
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, base.lower() + ".lua")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print("wrote %s (%d bytes)" % (path, len(text)))
    print("\nNOT yet verified. Compile it in game before shipping:")
    print("  the prefab must return a table from CompilePrefab, not nil.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    census = sub.add_parser("census", help="list engine-side candidates")
    census.add_argument("--min-refs", type=int, default=2)
    plan = sub.add_parser("plan", help="show where a base would be read from")
    plan.add_argument("name")
    build = sub.add_parser("build", help="read it from the game and emit .lua")
    build.add_argument("name")
    build.add_argument("--sources", type=int, default=3,
                       help="consumers to intersect (more = safer)")
    args = parser.parse_args()

    dump = Dump(args.dump or default_dump_path())
    return {"census": cmd_census, "plan": cmd_plan, "build": cmd_build}[
        args.command](dump, args)


if __name__ == "__main__":
    raise SystemExit(main())
