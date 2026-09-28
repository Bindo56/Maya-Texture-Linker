# Texture Set Linker

A Maya tool that turns a folder of PBR textures into finished shading networks.

Point it at a folder, press **Scan**, select your meshes, press **Auto-match**, press **Link textures**.
It groups the files into texture sets by name, pairs each set with a material in your selection, and
builds the `file` → converter → shader network for every map it recognises.

Written for Maya 2020 and newer (PySide2 or PySide6), Arnold optional.

## Why

Assigning a modern texture set by hand means, per material: six file nodes, six placement nodes, a normal
map converter, a displacement shader, and remembering that base colour is sRGB while everything else is
Raw. It is ten minutes of clicking per asset, and the colour space is the part everyone gets wrong. This
does it in one press, the same way every time.



https://github.com/user-attachments/assets/02a12c92-a97c-4b4f-a958-38340a357fad



## What it handles

| | |
|---|---|
| Channels | base colour, roughness, metalness, normal, ambient occlusion, height, emissive, opacity |
| Naming | `rock_wall_BaseColor.png`, `rockWallRoughness.exr`, `normal_rock_wall.png`, `crate_4k_diffuse.png` |
| UDIM | `name.1001.png` becomes one file node with Maya's UDIM tiling |
| Colour space | sRGB for colour maps, Raw for data maps, `alphaIsLuminance` for single-channel maps |
| Shaders | `standardSurface`, `aiStandardSurface`, and anything built on `lambert` |
| Legacy materials | an imported `lambert`/`blinn`/`phong` has no roughness or metalness input, so the tool offers to swap it for a PBR shader on the same objects |
| Normals | `aiNormalMap` when Arnold is loaded, otherwise `bump2d` in tangent-space mode |
| Height | optional `displacementShader` on the shading engine |
| Undo | one undo step per material, not one per node |
| Repath | finds file nodes whose textures have gone missing and repoints them at a folder |

Scalar maps connect through `outAlpha`, colour maps through `outColor`, decided by the attribute's own
type rather than a hardcoded list.

## Install

1. Copy the `texture_linker` folder into your Maya scripts folder:
   - Windows: `%USERPROFILE%\Documents\maya\scripts\`
   - macOS: `~/Library/Preferences/Autodesk/maya/scripts/`
   - Linux: `~/maya/scripts/`
2. In Maya's Script Editor, in a **Python** tab:

```python
import texture_linker
texture_linker.show()
```

To keep it on a shelf: with those two lines in the Python tab, choose **File → Save Script to Shelf**.

While you are working on the tool itself, this reloads it without restarting Maya:

```python
import importlib, texture_linker
from texture_linker import core, maya_build, ui
for module in (core, maya_build, ui, texture_linker):
    importlib.reload(module)
texture_linker.show()
```

## Options

**Upgrade legacy materials** (on by default). An FBX usually arrives on a `blinn` or `lambert`, which
predates PBR and has nowhere to put roughness or metalness - so half a texture set would be dropped. With
this on, that material is replaced by a `standardSurface` (or `aiStandardSurface` with Arnold) named
`<old>_std`, which takes over the same shading engine: every object keeps its assignment, and the old
shader is left in the scene in case you want it back. `lambert1` is refused, because everything
unassigned shares it.

**Height as displacement** (off by default). On, a height map builds a `displacementShader` on the
shading engine. Off, height is skipped and the log says so.

**Dry run**. Reports every connection it would make and builds nothing.

## Naming conventions

A filename is read as `<set name>` + `<channel>` + optional `<UDIM>`. The channel is whichever known word
sits nearest the end, so both `rock_wall_normal` and `normal_rock_wall` are the normal map of "rock wall".
Words like `4k`, `tex` and `final` are ignored, and `crate_BaseColor` is read as base colour for "crate",
not colour for "crate base".

Known spellings live in `CHANNEL_TOKENS` at the top of `core.py` - add your studio's and nothing else
changes.

## Layout

```
texture_linker/
  core.py        naming, grouping and matching - plain Python, no Maya
  maya_build.py  reading materials from a selection, building the network
  ui.py          the Qt window
tests/
  test_core.py   run with: python tests/test_core.py
```

The split is the point: the part with the rules in it runs, and is tested, outside Maya.

## Tests

```bash
python tests/test_core.py
```

Covers filename parsing, set grouping, UDIM detection, material matching and colour-space rules.

## Credits

The idea comes from a well-known technical art class brief - "make a Maya tool that lists textures in a
folder and assigns one to a selected mesh". This is my own take on it, written from scratch and aimed at
whole PBR texture sets rather than one file at a time.
