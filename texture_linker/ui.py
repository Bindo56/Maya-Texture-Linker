"""The Qt window. Thin on purpose: it collects choices and prints results, and every decision it makes
comes from core.py or maya_build.py.
"""

from __future__ import annotations

import os

try:  # Maya 2025 and later
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance
except ImportError:  # Maya 2020 - 2024
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance

import maya.cmds as cmds
import maya.OpenMayaUI as omui

from . import core, maya_build

WINDOW_OBJECT_NAME = "textureLinkerWindow"


def maya_main_window():
    """Maya's main window as a Qt object, so the tool docks and stacks like any other Maya panel."""
    pointer = omui.MQtUtil.mainWindow()
    return wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None


class TextureLinkerWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(TextureLinkerWindow, self).__init__(parent or maya_main_window())

        self.setObjectName(WINDOW_OBJECT_NAME)
        self.setWindowTitle("Texture Set Linker")
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self.resize(760, 560)

        self._sets = []
        self._pairs = {}

        self._build_ui()

    # ---------------------------------------------------------------- building

    def _build_ui(self):
        self.folder_field = QtWidgets.QLineEdit()
        self.folder_field.setPlaceholderText("Folder of textures...")
        browse_button = QtWidgets.QPushButton("Browse...")
        browse_button.clicked.connect(self._browse)
        self.recursive_box = QtWidgets.QCheckBox("Include subfolders")
        self.recursive_box.setChecked(True)
        scan_button = QtWidgets.QPushButton("Scan")
        scan_button.clicked.connect(self.scan)

        folder_row = QtWidgets.QHBoxLayout()
        folder_row.addWidget(self.folder_field)
        folder_row.addWidget(browse_button)
        folder_row.addWidget(self.recursive_box)
        folder_row.addWidget(scan_button)

        self.set_list = QtWidgets.QListWidget()
        self.set_list.currentItemChanged.connect(self._preview)
        self.material_list = QtWidgets.QListWidget()
        self.material_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        refresh_button = QtWidgets.QPushButton("Read materials from selection")
        refresh_button.clicked.connect(self.refresh_materials)

        self.preview = QtWidgets.QLabel("No preview")
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setMinimumHeight(180)
        self.preview.setStyleSheet("border: 1px solid #444; color: #888;")

        sets_column = QtWidgets.QVBoxLayout()
        sets_column.addWidget(QtWidgets.QLabel("Texture sets"))
        sets_column.addWidget(self.set_list)
        sets_column.addWidget(self.preview)

        materials_column = QtWidgets.QVBoxLayout()
        materials_column.addWidget(QtWidgets.QLabel("Materials"))
        materials_column.addWidget(self.material_list)
        materials_column.addWidget(refresh_button)

        columns = QtWidgets.QHBoxLayout()
        columns.addLayout(sets_column, 3)
        columns.addLayout(materials_column, 2)

        self.upgrade_box = QtWidgets.QCheckBox("Upgrade legacy materials")
        self.upgrade_box.setChecked(True)
        self.upgrade_box.setToolTip(
            "A lambert, blinn or phong has no roughness or metalness input.\n"
            "This swaps it for a standardSurface (or aiStandardSurface) on the same objects."
        )
        self.displacement_box = QtWidgets.QCheckBox("Height as displacement")
        self.dry_run_box = QtWidgets.QCheckBox("Dry run (report only)")
        match_button = QtWidgets.QPushButton("Auto-match")
        match_button.clicked.connect(self.auto_match)
        link_button = QtWidgets.QPushButton("Link textures")
        link_button.clicked.connect(self.link)
        repath_button = QtWidgets.QPushButton("Repath missing...")
        repath_button.clicked.connect(self.repath)

        options_row = QtWidgets.QHBoxLayout()
        options_row.addWidget(self.upgrade_box)
        options_row.addWidget(self.displacement_box)
        options_row.addWidget(self.dry_run_box)
        options_row.addStretch(1)
        options_row.addWidget(repath_button)
        options_row.addWidget(match_button)
        options_row.addWidget(link_button)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(folder_row)
        layout.addLayout(columns)
        layout.addLayout(options_row)
        layout.addWidget(self.log)

    # ----------------------------------------------------------------- actions

    def _browse(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose a texture folder", self.folder_field.text())
        if folder:
            self.folder_field.setText(folder)
            self.scan()

    def scan(self):
        folder = self.folder_field.text().strip()
        if not os.path.isdir(folder):
            self._say("Pick a folder that exists first.")
            return

        paths = core.scan(folder, recursive=self.recursive_box.isChecked())
        self._sets = core.build_sets(paths)
        self.set_list.clear()
        for texture_set in self._sets:
            label = "{}   [{}]{}".format(texture_set.name, ", ".join(texture_set.channels), "  UDIM" if texture_set.udim else "")
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, texture_set.name)
            self.set_list.addItem(item)

        skipped = len(paths) - sum(len(texture_set.maps) for texture_set in self._sets)
        self._say("Found {} files -> {} sets{}.".format(len(paths), len(self._sets), ", {} unrecognised".format(skipped) if skipped else ""))
        self.refresh_materials()

    def refresh_materials(self):
        self.material_list.clear()
        materials = maya_build.selected_materials()
        self.material_list.addItems(materials)
        if not materials:
            self._say("No materials in the selection - select some meshes.")

    def auto_match(self):
        materials = [self.material_list.item(row).text() for row in range(self.material_list.count())]
        if not self._sets or not materials:
            self._say("Scan a folder and select meshes first.")
            return

        self._pairs, unmatched, unused = core.match(self._sets, materials)
        self._say("Matched {} of {} materials.".format(len(self._pairs), len(materials)))
        for material, texture_set in sorted(self._pairs.items()):
            self._say("  {} <- {}".format(material, texture_set.name))
        for material in unmatched:
            self._say("  {} <- nothing close enough".format(material))
        if unused:
            self._say("  unused sets: " + ", ".join(texture_set.name for texture_set in unused))

        # Select the matched materials, so "Link textures" follows straight on.
        for row in range(self.material_list.count()):
            item = self.material_list.item(row)
            item.setSelected(item.text() in self._pairs)

    def link(self):
        selected = [item.text() for item in self.material_list.selectedItems()]
        if not selected:
            self._say("Select the materials to link, or press Auto-match.")
            return

        chosen_set = self._selected_set()
        dry_run = self.dry_run_box.isChecked()
        for material in selected:
            texture_set = self._pairs.get(material) or chosen_set
            if not texture_set:
                self._say("{}: no set matched, and none is selected in the list.".format(material))
                continue

            self._say("{} <- {}{}".format(material, texture_set.name, "  (dry run)" if dry_run else ""))

            target = material
            if self.upgrade_box.isChecked():
                target, note = maya_build.upgrade_material(material, dry_run=dry_run)
                if note:
                    self._say("  - " + note)

            for line in maya_build.build(texture_set, target, displacement=self.displacement_box.isChecked(), dry_run=dry_run):
                self._say(line)

        self.refresh_materials()

    def repath(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Search this folder for the missing textures")
        if not folder:
            return

        fixed, missing = maya_build.repath_missing(folder)
        self._say("Repathed {} file nodes, {} still missing.".format(len(fixed), len(missing)))
        for node, path in fixed:
            self._say("  {} -> {}".format(node, path))
        for node, path in missing:
            self._say("  {} still missing: {}".format(node, path))

    # ------------------------------------------------------------------ small

    def _selected_set(self):
        item = self.set_list.currentItem()
        if not item:
            return None
        name = item.data(QtCore.Qt.UserRole)
        return next((texture_set for texture_set in self._sets if texture_set.name == name), None)

    def _preview(self):
        texture_set = self._selected_set()
        path = texture_set.maps.get("base_color") if texture_set else None
        pixmap = QtGui.QPixmap(path) if path else QtGui.QPixmap()
        if pixmap.isNull():
            # Qt cannot read every format Maya can - TGA and EXR among them.
            self.preview.setText(os.path.basename(path) if path else "No preview")
            self.preview.setPixmap(QtGui.QPixmap())
            return
        self.preview.setPixmap(pixmap.scaled(self.preview.width(), self.preview.height(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def _say(self, message: str):
        self.log.appendPlainText(message)


def show():
    """Opens the tool, replacing any window already open."""
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.objectName() == WINDOW_OBJECT_NAME:
            widget.close()
            widget.deleteLater()

    window = TextureLinkerWindow()
    window.show()
    return window
