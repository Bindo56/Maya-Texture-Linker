"""Tests for the matching half of the tool. Plain Python - run them with:

    python tests/test_core.py

No Maya, no pytest, so they run in CI and in a couple of seconds on any machine.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from texture_linker import core  # noqa: E402

FAILURES = []


def check(name, got, expected):
    if got != expected:
        FAILURES.append("{}\n    got:      {!r}\n    expected: {!r}".format(name, got, expected))


def test_classify():
    check("plain suffix", core.classify("rock_wall_basecolor.png"), ("rock wall", "base_color", None))
    check("short suffix", core.classify("rock_wall_N.tga"), ("rock wall", "normal", None))
    check("camel case", core.classify("rockWallRoughness.exr"), ("rock wall", "roughness", None))
    check("prefix form", core.classify("normal_rock_wall.png"), ("rock wall", "normal", None))
    check("longest token wins", core.classify("crate_ambientOcclusion.png"), ("crate", "ao", None))
    check("noise words dropped", core.classify("crate_4k_diffuse_texture.png"), ("crate", "base_color", None))
    check("udim", core.classify("hero_prop_basecolor.1002.png"), ("hero prop", "base_color", "1002"))
    check("no channel", core.classify("reference_sheet.png"), ("reference sheet", None, None))


def test_build_sets():
    files = [
        "/t/rock_wall_basecolor.png", "/t/rock_wall_normal.png", "/t/rock_wall_roughness.png",
        "/t/crate_BaseColor.1001.png", "/t/crate_BaseColor.1002.png", "/t/crate_Normal.1001.png",
        "/t/notes.png",
    ]
    sets = core.build_sets(files)
    check("set count", [texture_set.name for texture_set in sets], ["crate", "rock wall"])

    crate, rock = sets
    check("crate channels", crate.channels, ["base_color", "normal"])
    check("crate is udim", crate.udim, True)
    check("crate keeps first tile", crate.maps["base_color"], "/t/crate_BaseColor.1001.png")
    check("rock channels", rock.channels, ["base_color", "normal", "roughness"])
    check("rock is not udim", rock.udim, False)


def test_matching():
    sets = core.build_sets([
        "/t/rock_wall_basecolor.png", "/t/crate_basecolor.png", "/t/barrel_basecolor.png",
    ])
    pairs, unmatched, unused = core.match(sets, ["M_rock_wall_01", "crateShader", "lambert1"])

    check("rock matched", pairs["M_rock_wall_01"].name, "rock wall")
    check("crate matched", pairs["crateShader"].name, "crate")
    check("lambert1 unmatched", unmatched, ["lambert1"])
    check("barrel unused", [texture_set.name for texture_set in unused], ["barrel"])

    # One set is never handed to two materials.
    pairs, _unmatched, _unused = core.match(core.build_sets(["/t/crate_basecolor.png"]), ["crate_A", "crate_B"])
    check("one set, one material", len(pairs), 1)


def test_udim_path():
    check("udim token", core.udim_path("/t/crate_BaseColor.1001.png").replace("\\", "/"), "/t/crate_BaseColor.<UDIM>.png")
    check("left alone", core.udim_path("/t/crate_BaseColor.png").replace("\\", "/"), "/t/crate_BaseColor.png")


def test_colour_space():
    check("base colour is srgb", core.is_colour("base_color"), True)
    check("normal is data", core.is_colour("normal"), False)
    check("roughness is scalar", core.is_scalar("roughness"), True)
    check("base colour is not scalar", core.is_scalar("base_color"), False)


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_"):
            test()

    for failure in FAILURES:
        print("FAIL " + failure)
    print("{} failed".format(len(FAILURES)) if FAILURES else "all checks passed")
    sys.exit(1 if FAILURES else 0)
