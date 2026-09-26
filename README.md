# PrefabReconstructor

Rebuilds a JWE3 **engine-side** prefab as a Lua one you can ship.

A prefab is engine-side when it is referenced as `Prefab = '<name>'` inside other
prefabs but has no top-level definition in the dump. A Lua prefab cannot inherit
one: it compiles and spawns an entity missing everything the base provided, and
nothing is logged. The remedy is to reconstruct it — see
`jwe3-prefab-compile-rules` rule 1.

**1,697** names qualify (runtime-verified: `api.entity.FindPrefab` returns nil for
each). 15 are referenced 10+ times and carry most of the weight.

## Why the content comes from the game, not the dump

The dump records an inheritor as `Prefab = '<name>'` plus that inheritor's own
overrides — the base's content is not in it. But `api.entity.FindPrefab` returns
the **fully flattened** prefab: inherited components, resolved `__property`
bindings, real values. So the base is read out of a live session.

## Why several consumers are read

A single consumer's flattened child is base content *plus that consumer's
overrides*, and the overrides sit nested inside `Components` — so subtracting
them textually deletes the very thing being recovered (an early version did
exactly that). Instead, several consumers are read and only what they **all
agree on** is kept: a key two consumers disagree on is an override, a key they
share came from the base.

Consumers are ranked by smallest local override, so the closest sources go first.

## Usage

    python reconstruct.py census --min-refs 10     # offline
    python reconstruct.py plan  BLDG_PathJoinPoint # offline
    python reconstruct.py build BLDG_PathJoinPoint # needs the game in a world

Output lands in `out/`. It is **not verified** — compile it in game before
shipping; the prefab must return a table from `CompilePrefab`, not nil.

## Schema checks

`core/schema.py` reads the kit's specdefs and enumnamers
(`JWE 3 Luas/Base Game/GameMain/Specdefs` and `.../Enumnamer`, 720 + 213):

* **component fields** — flags anything emitted that the component does not
  declare;
* **property types** — the `Type` a Property override needs under rule 7
  (`STRING`→`string`, `REFERENCE_TO_OBJECT`→`entity`, …);
* **enum members** — catches a rotted enum name *statically*. A value the namer
  does not know takes the whole prefab down with it. This reproduces the
  Indominus gate bug offline: `dinosaurgoalpoint` and `fence` are valid
  `SpatialFlags`, JWE2's `dinosaurgoalpoint_fence` is not.

## Validation

`build BLDG_FencePost` reproduces Inaki's hand-written reconstruction
field-for-field — Element, Network, Radius, Flags, both Foundation paths and the
`PostGUIShape` child's `CivilEngGUIShape Type='FencePost'`.

Known cosmetic difference: the output also carries `ComponentSources` and
`IncompleteComponents`. Both are valid JWE3 keys, but they are artefacts of the
flattened form rather than base content.

## Namespace warning

Registering a reconstruction under the vanilla global name (`BLDG_FencePost`) is
what makes an unedited inherited table resolve, but it collides with any other
mod doing the same. Prefix it and rewrite your own references whenever you
control the consumers; use the bare name only when you cannot edit them.
