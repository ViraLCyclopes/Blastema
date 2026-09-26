"""Extract the schemas the tool checks against.

Specdefs (component field schemas) and enumnamers (valid enum members) are not
shipped loose - they live inside `Win64/ovldata/GameMain/Main.ovl` and come out
with cobra-tools.  JWE3 1.4.1 yields 720 specdefs and 213 enumnamers.

They are worth having: a specdef says whether a component really declares a
field and what type a Property override needs, and an enumnamer says whether an
enum member exists at all - a name the namer does not know takes the whole
prefab down and nothing is logged.
"""

from __future__ import annotations

import os
import subprocess
import sys

HELP = (
    "Specdefs and enumnamers are not shipped loose.  Extract them once from\n"
    "the game with cobra-tools:\n\n"
    "    cd <cobra-tools>\n"
    "    python ovl_tool_cmd.py extract \\\n"
    "        \"<game>/Win64/ovldata/GameMain/Main.ovl\" \\\n"
    "        -o \"<somewhere>\" -g \"Jurassic World Evolution 3\"\n\n"
    "That writes .specdef and .enumnamer files (720 and 213 on JWE3 1.4.1).\n"
    "Point Settings at the folders, or use Extract schemas... to do it here."
)


def find_cobra() -> str | None:
    """The kit's authoritative cobra-tools checkout, if it is where we expect."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    kit = os.path.dirname(os.path.dirname(here))
    candidate = os.path.join(kit, "Cobra Dev", "cobra-tools-master")
    return candidate if os.path.isfile(os.path.join(candidate, "ovl_tool_cmd.py")) else None


def extract(game_root: str, destination: str, cobra_dir: str | None = None,
            timeout: float = 900.0) -> tuple[int, int]:
    """Pull GameMain/Main.ovl apart into `destination`.

    Returns (specdefs, enumnamers) written.  Raises on failure.
    """
    cobra_dir = cobra_dir or find_cobra()
    if not cobra_dir:
        raise RuntimeError(
            "cobra-tools not found. Set it in Settings, or extract by hand:\n\n" + HELP
        )
    source = os.path.join(game_root, "Win64", "ovldata", "GameMain", "Main.ovl")
    if not os.path.isfile(source):
        raise RuntimeError("no GameMain/Main.ovl under %s" % game_root)

    os.makedirs(destination, exist_ok=True)
    result = subprocess.run(
        [sys.executable, "ovl_tool_cmd.py", "extract", source,
         "-o", destination, "-g", "Jurassic World Evolution 3"],
        cwd=cobra_dir, capture_output=True, text=True, timeout=timeout,
    )
    specs = sum(1 for f in os.listdir(destination) if f.endswith(".specdef"))
    enums = sum(1 for f in os.listdir(destination) if f.endswith(".enumnamer"))
    if specs == 0 and enums == 0:
        tail = (result.stdout + result.stderr)[-600:]
        raise RuntimeError("extraction produced no schemas.\n%s" % tail)
    return specs, enums
