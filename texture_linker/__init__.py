"""Texture Set Linker - a Maya tool that turns a folder of PBR textures into shading networks.

    import texture_linker
    texture_linker.show()
"""

__version__ = "1.0.0"


def show():
    """Opens the window. Imported late so `import texture_linker` works outside Maya too."""
    from .ui import show as _show

    return _show()
