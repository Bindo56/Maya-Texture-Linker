"""Turning a folder of texture files into texture sets, and matching those to materials.

No Maya imports anywhere in this module - it is plain Python, so it runs and is tested outside Maya
(see tests/test_core.py). Everything that touches the scene lives in maya_build.py.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# Which words in a filename mean which shader input. Checked longest-first, so "base_color" wins over
# "color" and "ambientocclusion" over "ao". Add your studio's spellings here and the rest follows.
CHANNEL_TOKENS = {
    "base_color": ("basecolor", "albedo", "diffuse", "diff", "color", "col", "c", "d"),
    "roughness": ("roughness", "rough", "rgh", "r"),
    "metalness": ("metalness", "metallic", "metal", "mtl", "m"),
    "normal": ("normalgl", "normaldx", "normal", "nrml", "norm", "nrm", "nml", "n"),
    "ao": ("ambientocclusion", "occlusion", "ao"),
    "height": ("displacement", "height", "disp", "bump", "h"),
    "emissive": ("emissive", "emission", "emit", "glow", "e"),
    "opacity": ("transparency", "opacity", "alpha", "mask", "o"),
}

# Colour maps are sRGB; everything else is data and must stay Raw, or the shading is subtly wrong.
COLOUR_CHANNELS = ("base_color", "emissive")

# Single-channel maps: their file node reads luminance rather than RGB.
SCALAR_CHANNELS = ("roughness", "metalness", "ao", "height", "opacity")

IMAGE_EXTENSIONS = (
    ".png", ".tga", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr",
    ".psd", ".bmp", ".iff", ".pic", ".sgi", ".rgb", ".tx",
)

# Noise words that are part of a filename but say nothing about which set or channel it is.
IGNORED_TOKENS = ("texture", "textures", "tex", "map", "final", "v", "8k", "4k", "2k", "1k", "512", "1024", "2048", "4096")

# A UDIM tile is a four-digit number from 1001 up, on its own between separators.
UDIM_PATTERN = re.compile(r"(?:^|[._-])(1\d{3})(?:[._-]|$)")

_SEPARATORS = re.compile(r"[ _\-.]+")

# Longest tokens first, so short aliases never shadow the spelled-out ones.
_TOKEN_TO_CHANNEL = {
    token: channel
    for token, channel in sorted(
        ((token, channel) for channel, tokens in CHANNEL_TOKENS.items() for token in tokens),
        key=lambda pair: -len(pair[0]),
    )
}


@dataclass
class TextureSet:
    """Every map found for one material, keyed by channel."""

    name: str
    maps: dict = field(default_factory=dict)
    """channel -> file path. A UDIM set keeps its first tile here."""
    udim: bool = False

    @property
    def channels(self):
        return sorted(self.maps)

    def __repr__(self):
        return "TextureSet({!r}, {})".format(self.name, "+".join(self.channels) or "empty")


def tokenise(stem: str):
    """A filename stem split into lowercase words, with camelCase broken apart."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", stem)
    return [token.lower() for token in _SEPARATORS.split(spaced) if token]


def classify(filename: str):
    """A filename to (set name, channel or None, udim tile or None).

    The channel is whichever known token sits closest to the end of the name, so
    "rock_wall_normal.png" and "normalMap_rock_wall.png" both land on `normal` and both belong to the
    set "rock wall". Pairs of words are tried before single ones, so "crate_BaseColor" is a base colour
    map for "crate" rather than a colour map for "crate base".
    """
    stem, _ = os.path.splitext(os.path.basename(filename))

    udim_match = UDIM_PATTERN.search(stem)
    udim = udim_match.group(1) if udim_match else None
    if udim:
        stem = (stem[: udim_match.start(1)] + stem[udim_match.end(1):])

    tokens = tokenise(stem)

    channel = None
    consumed = ()
    for index in range(len(tokens) - 1, -1, -1):
        joined = tokens[index - 1] + tokens[index] if index > 0 else None
        if joined and joined in _TOKEN_TO_CHANNEL:
            channel = _TOKEN_TO_CHANNEL[joined]
            consumed = (index - 1, index)
            break
        if tokens[index] in _TOKEN_TO_CHANNEL:
            channel = _TOKEN_TO_CHANNEL[tokens[index]]
            consumed = (index,)
            break

    remaining = [
        token for index, token in enumerate(tokens)
        if index not in consumed and token not in IGNORED_TOKENS and not token.isdigit()
    ]
    return " ".join(remaining), channel, udim


def scan(folder: str, recursive: bool = True, extensions=IMAGE_EXTENSIONS):
    """Every texture file under `folder`, sorted, as absolute paths."""
    found = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if name.lower().endswith(tuple(extensions)):
                found.append(os.path.join(root, name))
        if not recursive:
            break
    return sorted(found)


def build_sets(paths):
    """Groups files into TextureSets by their set name. Files with no channel token are skipped."""
    sets = {}
    for path in paths:
        name, channel, udim = classify(path)
        if not channel or not name:
            continue

        texture_set = sets.setdefault(name, TextureSet(name=name))
        if udim:
            texture_set.udim = True
        # First tile wins, so a UDIM set points at 1001 rather than whichever tile sorted last.
        if channel not in texture_set.maps:
            texture_set.maps[channel] = path

    return [sets[name] for name in sorted(sets)]


def similarity(left: str, right: str) -> float:
    """0 to 1, on shared words - with a bonus when one name contains the other outright.

    Word-based rather than character-based, because "M_rock_wall_01" and "rock wall" are the same
    thing to an artist and nothing alike to an edit-distance.
    """
    left_tokens = {token for token in tokenise(left) if token not in IGNORED_TOKENS}
    right_tokens = {token for token in tokenise(right) if token not in IGNORED_TOKENS}
    if not left_tokens or not right_tokens:
        return 0.0

    shared = left_tokens & right_tokens
    score = len(shared) / len(left_tokens | right_tokens)

    flat_left = "".join(sorted(left_tokens))
    flat_right = "".join(sorted(right_tokens))
    if flat_left in flat_right or flat_right in flat_left:
        score = max(score, 0.9)

    return score


def match(sets, materials, threshold: float = 0.34):
    """Pairs each material with its best-scoring set.

    Greedy on the best score first, and every set and material is used once, so one good match never
    gets stolen by a worse one made earlier. Returns (pairs, unmatched materials, unused sets).
    """
    scored = sorted(
        (
            (similarity(texture_set.name, material), texture_set, material)
            for texture_set in sets
            for material in materials
        ),
        key=lambda item: (-item[0], item[1].name, item[2]),
    )

    pairs = {}
    used_sets = set()
    for score, texture_set, material in scored:
        if score < threshold or material in pairs or texture_set.name in used_sets:
            continue
        pairs[material] = texture_set
        used_sets.add(texture_set.name)

    unmatched = [material for material in materials if material not in pairs]
    unused = [texture_set for texture_set in sets if texture_set.name not in used_sets]
    return pairs, unmatched, unused


def udim_path(path: str) -> str:
    """The path with its tile number swapped for <UDIM>, which is how Maya stores a tiled texture."""
    directory, name = os.path.split(path)
    stem, extension = os.path.splitext(name)
    match_ = UDIM_PATTERN.search(stem)
    if not match_:
        return path
    stem = stem[: match_.start(1)] + "<UDIM>" + stem[match_.end(1):]
    return os.path.join(directory, stem + extension)


def is_colour(channel: str) -> bool:
    return channel in COLOUR_CHANNELS


def is_scalar(channel: str) -> bool:
    return channel in SCALAR_CHANNELS
