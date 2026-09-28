"""Everything that touches the Maya scene: reading materials off a selection, and building the shading
network for a texture set.

Kept apart from core.py so the matching logic can be tested outside Maya, and so this file stays small
enough to read in one go.
"""

from __future__ import annotations

import os

import maya.cmds as cmds

from . import core

# Which material attribute each channel feeds, per shader type. A shader that is not listed falls back to
# the lambert row, which every legacy Maya material inherits from.
SHADER_INPUTS = {
    "standardSurface": {
        "base_color": "baseColor",
        "roughness": "specularRoughness",
        "metalness": "metalness",
        "emissive": "emissionColor",
        "opacity": "opacity",
        "normal": "normalCamera",
    },
    "aiStandardSurface": {
        "base_color": "baseColor",
        "roughness": "specularRoughness",
        "metalness": "metalness",
        "emissive": "emissionColor",
        "opacity": "opacity",
        "normal": "normalCamera",
    },
    "lambert": {
        "base_color": "color",
        "emissive": "incandescence",
        "opacity": "transparency",
        "normal": "normalCamera",
    },
}

# A file node needs the placement node's outputs to respect UV tiling and filtering. Maya connects these
# for you in the Hypershade; from script they have to be named.
PLACEMENT_LINKS = (
    ("coverage", "coverage"), ("translateFrame", "translateFrame"), ("rotateFrame", "rotateFrame"),
    ("mirrorU", "mirrorU"), ("mirrorV", "mirrorV"), ("stagger", "stagger"),
    ("wrapU", "wrapU"), ("wrapV", "wrapV"), ("repeatUV", "repeatUV"), ("offset", "offset"),
    ("rotateUV", "rotateUV"), ("noiseUV", "noiseUV"), ("vertexUvOne", "vertexUvOne"),
    ("vertexUvTwo", "vertexUvTwo"), ("vertexUvThree", "vertexUvThree"),
    ("vertexCameraOne", "vertexCameraOne"), ("outUV", "uv"), ("outUvFilterSize", "uvFilterSize"),
)

# Maya's UDIM (Mari) tiling mode.
UDIM_TILING_MODE = 3

# Pre-PBR shaders. They have no roughness or metalness input at all, which is why an imported FBX's
# material silently drops half a texture set - so the tool offers to swap them for a modern one.
LEGACY_SHADERS = ("lambert", "blinn", "phong", "phongE", "anisotropic", "surfaceShader")

# Maya's default material: shared by everything unassigned, so replacing it would reshade the whole scene.
DEFAULT_MATERIAL = "lambert1"


def arnold_available() -> bool:
    return "aiStandardSurface" in (cmds.allNodeTypes() or [])


def selected_materials():
    """Every material assigned to the current selection, in the order first seen.

    Goes selection -> shape -> shading engine -> whatever drives its surfaceShader, so it works with any
    renderer's shader rather than only the ones built on lambert.
    """
    shapes = cmds.ls(selection=True, dagObjects=True, shapes=True, noIntermediate=True) or []
    materials = []
    for shape in shapes:
        for shading_engine in cmds.listConnections(shape, type="shadingEngine") or []:
            for material in cmds.listConnections(shading_engine + ".surfaceShader", source=True, destination=False) or []:
                if material not in materials:
                    materials.append(material)
    return materials


def shading_engines(material: str):
    """Every shading group this material drives.

    More than one is normal: per-face assignments and imported meshes both produce it, and upgrading only
    the first would leave the rest of the model on the old shader.
    """
    found = cmds.listConnections(material, type="shadingEngine") or []
    return list(dict.fromkeys(found))


def shading_engine(material: str):
    groups = shading_engines(material)
    return groups[0] if groups else None


def _shader_inputs(material: str):
    return SHADER_INPUTS.get(cmds.nodeType(material), SHADER_INPUTS["lambert"])


def is_legacy(material: str) -> bool:
    return cmds.nodeType(material) in LEGACY_SHADERS


def upgrade_material(material: str, dry_run: bool = False):
    """Swaps a legacy shader for a PBR one on the same objects. Returns (material to use, note).

    The new shader takes over the old one's shading engine, so every object keeps its assignment and the
    old shader is left in the scene untouched, in case you want it back.
    """
    if not is_legacy(material):
        return material, None
    if material == DEFAULT_MATERIAL:
        return material, "lambert1 is Maya's default material - assign a material of its own first"

    groups = shading_engines(material)
    if not groups:
        return material, "no shading engine to move across"

    shader_type = "aiStandardSurface" if arnold_available() else "standardSurface"
    if dry_run:
        return material, "would become a {} ({})".format(shader_type, material + "_std")

    upgraded = cmds.shadingNode(shader_type, asShader=True, skipSelect=True, name=material + "_std")

    # Carry the old colour over, so channels the texture set has no map for do not turn grey.
    if cmds.attributeQuery("color", node=material, exists=True):
        colour = cmds.getAttr(material + ".color")[0]
        cmds.setAttr(upgraded + ".baseColor", colour[0], colour[1], colour[2], type="double3")

    for group in groups:
        cmds.connectAttr(upgraded + ".outColor", group + ".surfaceShader", force=True)

    note = "{} -> {} ({})".format(cmds.nodeType(material), shader_type, upgraded)
    if len(groups) > 1:
        note += ", on {} shading groups".format(len(groups))
    return upgraded, note


def _is_single_number(plug: str) -> bool:
    """True for a float attribute such as specularRoughness, false for a colour such as baseColor.

    Decides whether a file node feeds it through outAlpha or outColor - connect a colour into a float and
    Maya refuses the connection.
    """
    try:
        return cmds.getAttr(plug, type=True) in ("double", "float", "doubleLinear", "long", "short")
    except (RuntimeError, ValueError):
        return False


def _disconnect_input(plug: str):
    """Clears whatever currently drives `plug`, so re-running the tool replaces rather than fails."""
    for source in cmds.listConnections(plug, source=True, destination=False, plugs=True) or []:
        cmds.disconnectAttr(source, plug)


def create_file_node(path: str, channel: str, udim: bool, name: str):
    """A file node and its place2dTexture, set up for this channel's colour space and tiling."""
    file_node = cmds.shadingNode("file", asTexture=True, isColorManaged=True, skipSelect=True, name=name + "_file")
    placement = cmds.shadingNode("place2dTexture", asUtility=True, skipSelect=True, name=name + "_place2d")
    for out_attr, in_attr in PLACEMENT_LINKS:
        cmds.connectAttr("{}.{}".format(placement, out_attr), "{}.{}".format(file_node, in_attr), force=True)

    texture_path = core.udim_path(path) if udim else path
    cmds.setAttr(file_node + ".fileTextureName", texture_path, type="string")
    if udim:
        cmds.setAttr(file_node + ".uvTilingMode", UDIM_TILING_MODE)

    # Colour management: only the colour maps are sRGB. Left to the file rules, a roughness map imported
    # as sRGB is quietly wrong - the usual cause of "my roughness looks flat".
    cmds.setAttr(file_node + ".ignoreColorSpaceFileRules", True)
    cmds.setAttr(file_node + ".colorSpace", "sRGB" if core.is_colour(channel) else "Raw", type="string")
    if core.is_scalar(channel):
        cmds.setAttr(file_node + ".alphaIsLuminance", True)

    return file_node


def _connect_normal(file_node: str, material: str, plug: str, name: str):
    """Tangent-space normals need a converter between the file and the shader."""
    if arnold_available():
        converter = cmds.shadingNode("aiNormalMap", asUtility=True, skipSelect=True, name=name + "_normalMap")
        cmds.connectAttr(file_node + ".outColor", converter + ".input", force=True)
        cmds.connectAttr(converter + ".outValue", plug, force=True)
    else:
        converter = cmds.shadingNode("bump2d", asUtility=True, skipSelect=True, name=name + "_bump2d")
        cmds.setAttr(converter + ".bumpInterp", 1)  # tangent-space normal, not a height bump
        cmds.connectAttr(file_node + ".outAlpha", converter + ".bumpValue", force=True)
        cmds.connectAttr(converter + ".outNormal", plug, force=True)
    return converter


def _connect_opacity(file_node: str, material: str, plug: str, name: str):
    """standardSurface wants opacity; the legacy shaders want transparency, which is its opposite."""
    if plug.endswith(".transparency"):
        reverse = cmds.shadingNode("reverse", asUtility=True, skipSelect=True, name=name + "_reverse")
        cmds.connectAttr(file_node + ".outColor", reverse + ".input", force=True)
        cmds.connectAttr(reverse + ".output", plug, force=True)
        return reverse

    cmds.connectAttr(file_node + ".outColor", plug, force=True)
    return None


def _connect_displacement(file_node: str, material: str, name: str):
    """Height goes to the shading engine, not the shader."""
    groups = shading_engines(material)
    if not groups:
        return None

    node = cmds.shadingNode("displacementShader", asShader=True, skipSelect=True, name=name + "_displacement")
    cmds.connectAttr(file_node + ".outAlpha", node + ".displacement", force=True)
    for group in groups:
        cmds.connectAttr(node + ".displacement", group + ".displacementShader", force=True)
    return node


def build(texture_set, material: str, displacement: bool = False, dry_run: bool = False):
    """Wires every map in `texture_set` into `material`. Returns the lines to show in the log.

    One undo chunk, so an artist's ctrl+Z takes the whole assignment back rather than one node at a time.
    """
    inputs = _shader_inputs(material)
    lines = []

    if not dry_run:
        cmds.undoInfo(openChunk=True, chunkName="Link textures to " + material)
    try:
        for channel in texture_set.channels:
            path = texture_set.maps[channel]

            if channel == "height" and displacement:
                target = "displacement (shading engine)"
            elif channel == "height":
                lines.append("  - skipped height: {} (tick Height as displacement to use it)".format(os.path.basename(path)))
                continue
            elif channel == "ao":
                # Nothing in a standard PBR shader takes AO on its own; it belongs multiplied into base
                # colour or in the lighting, so it is reported rather than silently dropped.
                lines.append("  - skipped {}: {} (no AO input on {})".format(channel, os.path.basename(path), cmds.nodeType(material)))
                continue
            elif channel in inputs:
                target = inputs[channel]
            else:
                hint = " - tick Upgrade legacy materials" if is_legacy(material) else ""
                lines.append("  - skipped {}: {} (no {} input on {}{})".format(
                    channel, os.path.basename(path), channel, cmds.nodeType(material), hint))
                continue

            lines.append("  - {} -> {}.{}".format(os.path.basename(path), material, target))
            if dry_run:
                continue

            name = "{}_{}".format(material, channel)
            file_node = create_file_node(path, channel, texture_set.udim, name)

            if channel == "height" and displacement:
                _connect_displacement(file_node, material, name)
                continue

            plug = "{}.{}".format(material, target)
            _disconnect_input(plug)

            if channel == "normal":
                _connect_normal(file_node, material, plug, name)
            elif channel == "opacity":
                _connect_opacity(file_node, material, plug, name)
            else:
                output = ".outAlpha" if _is_single_number(plug) else ".outColor"
                cmds.connectAttr(file_node + output, plug, force=True)

            # An emissive map does nothing until emission itself is turned up.
            if channel == "emissive" and cmds.attributeQuery("emission", node=material, exists=True):
                cmds.setAttr(material + ".emission", 1)
    finally:
        if not dry_run:
            cmds.undoInfo(closeChunk=True)

    return lines


def repath_missing(root: str):
    """Points every file node whose texture has gone missing at a file of the same name under `root`.

    The other half of this job in practice: a scene that came from another machine with broken paths.
    """
    index = {}
    for folder, _dirs, files in os.walk(root):
        for name in files:
            index.setdefault(name.lower(), os.path.join(folder, name))

    fixed, still_missing = [], []
    for file_node in cmds.ls(type="file") or []:
        path = cmds.getAttr(file_node + ".fileTextureName")
        if not path or os.path.exists(path.replace("<UDIM>", "1001")):
            continue

        name = os.path.basename(path).replace("<UDIM>", "1001")
        replacement = index.get(name.lower())
        if replacement:
            if "<UDIM>" in path:
                replacement = core.udim_path(replacement)
            cmds.setAttr(file_node + ".fileTextureName", replacement, type="string")
            fixed.append((file_node, replacement))
        else:
            still_missing.append((file_node, path))

    return fixed, still_missing
