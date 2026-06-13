


"""
PyQt6 GUI for the Parametric Fingerboard Builder application.
Implements the main window, parameter entry forms, preview rendering, and STL export functionality using PyQt6 and pyqtgraph.opengl.
"""

import tempfile
from pathlib import Path
from typing import cast, Literal
import numpy as np
import trimesh
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel, QPushButton, QFileDialog, QMessageBox, QGroupBox, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph.opengl as gl
from pyqtgraph.Qt import QtGui

from parametric_fingerboard.model import (
    FingerboardParameters,
    SideParameters,
    ExportType,
    build_fingerboard,
    _prepare_fingerboard,
    export_stl,
)

GLOBAL_PARAMETER_ROWS = (
    ("hand_span", "Hand span"),
    ("edge_rounding", "Edge rounding"),
    ("side_margin", "Side margin"),
    ("top_margin", "Top margin"),
    ("center_bulk", "Center bulk"),
    ("edge_depth", "Edge depth"),
    ("cord_hole_diameter", "Cord hole diameter"),
)

ADVANCED_PARAMETER_ROWS = (
    ("bottom_layer_thickness", "Bottom layer thickness"),
    ("side_chamfer", "Side chamfer"),
    ("top_bottom_chamfer", "Top bottom chamfer"),
    ("finger_groove_factor", "Groove curvature factor"),
)

SIDE_PARAMETER_ROWS = (
    ("index_middle", "<span>&Delta; Index Middle</span>"),
    ("middle_ring", "<span>&Delta; Middle Ring</span>"),
    ("ring_pinky", "<span>&Delta; Ring Pinky</span>"),
)

class FingerboardGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parametric Fingerboard Builder")
        self.setMinimumSize(1200, 760)
        self.resize(1540, 920)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_label.setMinimumWidth(0)
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.warning_label.setMinimumWidth(0)
        self.warning_label.setStyleSheet("color: #8a1f1f; background: #fbeaea; padding: 4px; border-radius: 3px;")
        self.warning_label.hide()
        self._last_edited_global_key: str | None = None
        self.global_entries = {}
        self.left_entries = {}
        self.right_entries = {}
        self.advanced_entries = {}
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._run_scheduled_preview)

        self._build_layout()
        self._set_defaults()

    def _build_layout(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # Controls (left)
        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_scroll.setWidget(controls_widget)

        # Global parameters
        global_group = QGroupBox("Global Parameters")
        global_form = QFormLayout(global_group)
        for key, label_text in GLOBAL_PARAMETER_ROWS:
            entry = QLineEdit()
            self.global_entries[key] = entry
            global_form.addRow(QLabel(label_text), entry)
        controls_layout.addWidget(global_group)

        # Advanced parameters (collapsible)
        self.advanced_group = QGroupBox("Advanced")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        self.advanced_group.toggled.connect(self._toggle_advanced_section)
        advanced_form = QFormLayout(self.advanced_group)
        for key, label_text in ADVANCED_PARAMETER_ROWS:
            entry = QLineEdit()
            self.advanced_entries[key] = entry
            advanced_form.addRow(QLabel(label_text), entry)
        controls_layout.addWidget(self.advanced_group)

        # Hand parameters
        hands_group = QGroupBox("Hand Parameters")
        hands_layout = QHBoxLayout(hands_group)
        right_group = QGroupBox("Right Hand")
        right_form = QFormLayout(right_group)
        for key, label_text in SIDE_PARAMETER_ROWS:
            entry = QLineEdit()
            self.right_entries[key] = entry
            right_form.addRow(QLabel(label_text), entry)
        left_group = QGroupBox("Left Hand")
        left_form = QFormLayout(left_group)
        for key, label_text in SIDE_PARAMETER_ROWS:
            entry = QLineEdit()
            self.left_entries[key] = entry
            left_form.addRow(QLabel(label_text), entry)
        hands_layout.addWidget(right_group)
        hands_layout.addWidget(left_group)
        controls_layout.addWidget(hands_group)

        # Actions
        actions_widget = QWidget()
        actions_layout = QVBoxLayout(actions_widget)
        export_btn = QPushButton("Export STL")
        export_btn.clicked.connect(self.on_export)
        actions_layout.addWidget(export_btn)
        actions_layout.addWidget(self.status_label)
        actions_layout.addWidget(self.warning_label)
        controls_layout.addWidget(actions_widget)
        controls_layout.addStretch(1)

        main_layout.addWidget(controls_scroll, 0)

        # 3D Preview (right)
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        self.gl_view = gl.GLViewWidget()
        self.gl_view.setBackgroundColor('w')
        self.gl_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.gl_view)
        main_layout.addWidget(preview_widget, 1)

    def _toggle_advanced_section(self):
        # No-op: QGroupBox handles show/hide. Just trigger preview update.
        self._schedule_preview()

    # No need for _add_side_rows/_add_form_row: handled in _build_layout

    # PyQt: connect signals for all QLineEdit widgets
        

    def _schedule_preview(self):
        self._preview_timer.start(800)

    def _run_scheduled_preview(self):
        self.on_preview(show_dialog=False)

    def _set_defaults(self):
        defaults = {
            "hand_span": "68.0",
            "edge_rounding": "2.0",
            "side_margin": "8.0",
            "top_margin": "8.0",
            "center_bulk": "15.0",
            "edge_depth": "20.0",
            "cord_hole_diameter": "8.0",
        }
        advanced_defaults = {
            "bottom_layer_thickness": "5.0",
            "side_chamfer": "5.0",
            "top_bottom_chamfer": "2.0",
            "finger_groove_factor": "0.74",
        }
        self.min_side_margin = 5.0
        self.min_top_margin = 5.0
        for k, v in defaults.items():
            self.global_entries[k].setText(v)
        for k, v in advanced_defaults.items():
            self.advanced_entries[k].setText(v)
        side_defaults = {
            "index_middle": "0",
            "middle_ring": "0",
            "ring_pinky": "0",
        }
        for values in (self.left_entries, self.right_entries):
            for k, v in side_defaults.items():
                values[k].setText(v)
        # Connect signals for all QLineEdit widgets
        for entry in list(self.global_entries.values()) + list(self.left_entries.values()) + list(self.right_entries.values()) + list(self.advanced_entries.values()):
            entry.textChanged.connect(self._schedule_preview)
        for key, entry in self.global_entries.items():
            entry.textEdited.connect(lambda _text, k=key: self._mark_last_edited_global_key(k))
        self._schedule_preview()

    def _mark_last_edited_global_key(self, key: str) -> None:
        self._last_edited_global_key = key

    def _bulk_cord_adjustment_preference(self) -> Literal["center_bulk", "cord_hole_diameter", "auto"]:
        if self._last_edited_global_key == "center_bulk":
            return "center_bulk"
        if self._last_edited_global_key == "cord_hole_diameter":
            return "cord_hole_diameter"
        return "auto"

    def _set_warning_text(self, text: str = "") -> None:
        if text.strip():
            self.warning_label.setText(f"Warning:\n{text.strip()}")
            self.warning_label.show()
        else:
            self.warning_label.clear()
            self.warning_label.hide()

    def _apply_clamped_values_from_warning(self, warning: str) -> None:
        def _set_if_changed(entry: QLineEdit | None, new_value: str) -> None:
            if entry is None:
                return
            if entry.text().strip() == new_value:
                return
            prev = entry.blockSignals(True)
            try:
                entry.setText(new_value)
            finally:
                entry.blockSignals(prev)

        for line in warning.splitlines():
            if line.startswith("side_chamfer "):
                match = line.rsplit("Clamped to ", 1)
                if len(match) == 2:
                    _set_if_changed(self.advanced_entries.get("side_chamfer"), match[1].split(" mm", 1)[0])
            elif line.startswith("top/bottom chamfer "):
                match = line.rsplit("Clamped to ", 1)
                if len(match) == 2:
                    _set_if_changed(self.advanced_entries.get("top_bottom_chamfer"), match[1].split(" mm", 1)[0])
            elif line.startswith("center_bulk "):
                match = line.rsplit("Clamped to ", 1)
                if len(match) == 2:
                    _set_if_changed(self.global_entries.get("center_bulk"), match[1].split(" mm", 1)[0])
            elif line.startswith("cord_hole_diameter "):
                match = line.rsplit("Clamped to ", 1)
                if len(match) == 2:
                    _set_if_changed(self.global_entries.get("cord_hole_diameter"), match[1].split(" mm", 1)[0])
            elif line.startswith("finger_groove_factor "):
                match = line.rsplit("Clamped to ", 1)
                if len(match) == 2:
                    _set_if_changed(self.advanced_entries.get("finger_groove_factor"), match[1].split(" ", 1)[0])
            elif line.startswith("edge_rounding "):
                match = line.rsplit("Clamped to ", 1)
                if len(match) == 2:
                    _set_if_changed(self.global_entries.get("edge_rounding"), match[1].split(" ", 1)[0])

    def _float_value(self, entry_map, key):
        value = float(entry_map[key].text().strip())
        if key == "side_margin":
            min_val = getattr(self, "min_side_margin", 0.0)
            if value < min_val:
                entry_map[key].setText(str(min_val))
                raise ValueError(f"side_margin must be >= min_side_margin ({min_val})")
            return value
        if key == "top_margin":
            min_val = getattr(self, "min_top_margin", 0.0)
            if value < min_val:
                entry_map[key].setText(str(min_val))
                raise ValueError(f"top_margin must be >= min_top_margin ({min_val})")
            return value
        return value

    def _collect_params(self) -> FingerboardParameters:
        """
        Collects all parameter values from entry widgets and returns a FingerboardParameters object.

        Returns:
            FingerboardParameters: The collected parameters for the fingerboard.
        """
        left = SideParameters(
            index_middle=self._float_value(self.left_entries, "index_middle"),
            middle_ring=self._float_value(self.left_entries, "middle_ring"),
            ring_pinky=self._float_value(self.left_entries, "ring_pinky"),
        )

        right = SideParameters(
            index_middle=self._float_value(self.right_entries, "index_middle"),
            middle_ring=self._float_value(self.right_entries, "middle_ring"),
            ring_pinky=self._float_value(self.right_entries, "ring_pinky"),
        )

        return FingerboardParameters(
            hand_span=self._float_value(self.global_entries, "hand_span"),
            edge_rounding=self._float_value(self.global_entries, "edge_rounding"),
            left=left,
            right=right,
            side_margin=self._float_value(self.global_entries, "side_margin"),
            top_margin=self._float_value(self.global_entries, "top_margin"),
            center_bulk=self._float_value(self.global_entries, "center_bulk"),
            edge_depth=self._float_value(self.global_entries, "edge_depth"),
            # Advanced
            bottom_layer_thickness=self._float_value(self.advanced_entries, "bottom_layer_thickness"),
            side_chamfer=self._float_value(self.advanced_entries, "side_chamfer"),
            top_bottom_chamfer=self._float_value(self.advanced_entries, "top_bottom_chamfer"),
            cord_hole_diameter=self._float_value(self.global_entries, "cord_hole_diameter"),
            finger_groove_factor=self._float_value(self.advanced_entries, "finger_groove_factor"),
        )

    def _add_coordinate_axes(self, center: np.ndarray, size: float) -> None:
        """Adds a world-space XYZ axis gizmo to the preview scene.

        The axis is placed near the model center so it rotates consistently with the
        model as the user orbits the camera.
        """
        axis_length = max(10.0, size * 0.35)
        axis = gl.GLAxisItem()
        axis.setSize(x=axis_length, y=axis_length, z=axis_length)
        axis.translate(float(center[0]), float(center[1]), float(center[2]))
        self.gl_view.addItem(axis)

        # Label axis tips if GLTextItem is available in the installed pyqtgraph.
        text_item_cls = getattr(gl, "GLTextItem", None)
        if text_item_cls is None:
            return

        labels = (
            ("X", np.array([axis_length, 0.0, 0.0], dtype=float)),
            ("Y", np.array([0.0, axis_length, 0.0], dtype=float)),
            ("Z", np.array([0.0, 0.0, axis_length], dtype=float)),
        )
        for label, offset in labels:
            pos = center + offset
            try:
                item = text_item_cls(pos=pos, text=label)
            except TypeError:
                # Fallback constructor shape for older/newer GLTextItem variants.
                item = text_item_cls()
                if hasattr(item, "setData"):
                    item.setData(pos=pos, text=label)
                else:
                    continue
            self.gl_view.addItem(item)

    def _render_preview(self, stl_path: Path) -> None:
        mesh = trimesh.load_mesh(stl_path)
        # Remove previous mesh
        for item in self.gl_view.items[:]:
            self.gl_view.removeItem(item)
        # Prepare mesh data
        vertices = mesh.vertices
        faces = mesh.faces
        normals = mesh.face_normals
        light_dir = np.array([0.4, -0.55, 0.75], dtype=float)
        light_dir /= np.linalg.norm(light_dir)
        brightness = np.clip(normals @ light_dir, 0.0, 1.0)
        brightness = 0.22 + 0.78 * brightness
        # Set model color to medium gray
        base_color = np.array([0.5, 0.5, 0.5])
        face_colors = np.column_stack([
            np.clip(base_color[0] * brightness, 0.0, 1.0),
            np.clip(base_color[1] * brightness, 0.0, 1.0),
            np.clip(base_color[2] * brightness, 0.0, 1.0),
            np.ones_like(brightness),
        ])
        # pyqtgraph expects faces as int32
        meshdata = gl.MeshData(vertexes=vertices, faces=faces.astype(np.int32), faceColors=face_colors)
        mesh_item = gl.GLMeshItem(meshdata=meshdata, smooth=False, drawFaces=True, drawEdges=False)
        self.gl_view.addItem(mesh_item)
        # Center and scale view
        bounds = mesh.bounds
        mins = bounds[0]
        maxs = bounds[1]
        center = (mins + maxs) / 2
        size = (maxs - mins).max()
        self._add_coordinate_axes(center, float(size))
        self.gl_view.setCameraPosition(pos=QtGui.QVector3D(center[0], center[1], center[2] + size * 1.5), distance=size * 2)
        self.gl_view.opts['center'] = QtGui.QVector3D(*center)

    def _render_error_preview(self, message: str) -> None:
        for item in self.gl_view.items[:]:
            self.gl_view.removeItem(item)
        error_label = QLabel(f"Invalid parameters:\n{message}")
        error_label.setStyleSheet("color: #8a1f1f; background: #fbeaea; font-size: 14px;")
        self.status_label.setText(f"Preview failed: {message}")
        self._set_warning_text(message)

    def on_preview(self, show_dialog: bool = True) -> None:
        try:
            params = self._collect_params()
            bulk_cord_preference = self._bulk_cord_adjustment_preference()
            prepared = _prepare_fingerboard(params, bulk_cord_preference=bulk_cord_preference)
            shape, warning = build_fingerboard(
                params,
                prepared=prepared,
                bulk_cord_preference=bulk_cord_preference,
            )
            # Swap length and width for output
            board_width, board_length, board_height = (
                prepared.board_length,
                prepared.board_width,
                prepared.board_height,
            )
            with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            export_stl(params, tmp_path, shape=shape, prepared=prepared)
            self._render_preview(tmp_path)
            msg = (
                "Preview updated | "
                f"L={board_length:.1f} mm, W={board_width:.1f} mm, H={board_height:.1f} mm"
            )
            self.status_label.setText(msg)
            if warning:
                self._apply_clamped_values_from_warning(warning)
                self._set_warning_text(warning)
                if show_dialog:
                    QMessageBox.warning(self, "Parameters Adjusted", warning)
            else:
                self._set_warning_text("")
        except Exception as exc:
            self.status_label.setText(f"Preview failed: {exc}")
            self._render_error_preview(str(exc))
            if show_dialog:
                QMessageBox.critical(self, "Preview failed", str(exc))

    def on_export(self) -> None:
        try:
            params = self._collect_params()
            bulk_cord_preference = self._bulk_cord_adjustment_preference()
            prepared = _prepare_fingerboard(params, bulk_cord_preference=bulk_cord_preference)
            # Swap length and width for output
            board_width, board_length, board_height = (
                prepared.board_length,
                prepared.board_width,
                prepared.board_height,
            )
            export_filters = (
                "STL mesh (*.stl);;"
                "3MF mesh (*.3mf);;"
                "STEP model (*.step *.stp);;"
                "AMF mesh (*.amf);;"
                "SVG drawing (*.svg);;"
                "TJS model (*.json *.tjs);;"
                "DXF drawing (*.dxf);;"
                "VRML model (*.wrl *.vrml);;"
                "VTP model (*.vtp);;"
                "BREP model (*.brep);;"
                "BIN BREP model (*.bin)"
            )
            path, selected_filter = QFileDialog.getSaveFileName(
                self,
                "Save Model",
                "",
                export_filters,
            )
            if not path:
                self.status_label.setText("Export cancelled")
                self._set_warning_text("")
                return

            filter_to_export: dict[str, tuple[ExportType, str]] = {
                "STL": ("STL", ".stl"),
                "3MF": ("3MF", ".3mf"),
                "STEP": ("STEP", ".step"),
                "AMF": ("AMF", ".amf"),
                "SVG": ("SVG", ".svg"),
                "TJS": ("TJS", ".tjs"),
                "DXF": ("DXF", ".dxf"),
                "VRML": ("VRML", ".wrl"),
                "VTP": ("VTP", ".vtp"),
                "BREP": ("BREP", ".brep"),
                "BIN": ("BIN", ".bin"),
            }

            export_type: ExportType | None = None
            default_ext = ""
            for key, (etype, ext) in filter_to_export.items():
                if selected_filter.startswith(key):
                    export_type = etype
                    default_ext = ext
                    break

            target_path = Path(path)
            if default_ext and target_path.suffix == "":
                target_path = target_path.with_suffix(default_ext)

            if export_type is None and target_path.suffix:
                suffix_map: dict[str, ExportType] = {
                    ".stl": "STL",
                    ".3mf": "3MF",
                    ".step": "STEP",
                    ".stp": "STEP",
                    ".amf": "AMF",
                    ".svg": "SVG",
                    ".json": "TJS",
                    ".tjs": "TJS",
                    ".dxf": "DXF",
                    ".wrl": "VRML",
                    ".vrml": "VRML",
                    ".vtp": "VTP",
                    ".brep": "BREP",
                    ".bin": "BIN",
                }
                export_type = suffix_map.get(target_path.suffix.lower())

            shape, warning = build_fingerboard(
                params,
                prepared=prepared,
                bulk_cord_preference=bulk_cord_preference,
            )
            output = export_stl(
                params,
                target_path,
                shape=shape,
                prepared=prepared,
                export_type=export_type,
            )
            output_path = Path(output)
            self.status_label.setText(
                f"{cast(str, export_type or 'AUTO')} exported | L={board_length:.1f} mm, W={board_width:.1f} mm, H={board_height:.1f} mm | {output_path.name}"
            )
            self.status_label.setToolTip(str(output_path))
            if warning:
                self._apply_clamped_values_from_warning(warning)
                self._set_warning_text(warning)
                QMessageBox.warning(self, "Parameters Adjusted", warning)
            else:
                self._set_warning_text("")
        except Exception as exc:
            self.status_label.setText(f"Export failed: {exc}")
            self._set_warning_text(str(exc))
            QMessageBox.critical(self, "Export failed", str(exc))


def run_app():
    app = QApplication([])
    window = FingerboardGUI()
    window.show()
    app.exec()
