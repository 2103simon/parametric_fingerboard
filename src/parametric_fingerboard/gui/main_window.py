


"""
PyQt6 GUI for the Parametric Fingerboard Builder application.
Implements the main window, parameter entry forms, preview rendering, and STL export functionality using PyQt6 and pyqtgraph.opengl.
"""

import tempfile
from pathlib import Path
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
    build_fingerboard,
    _prepare_fingerboard,
    export_stl,
)



class FingerboardGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parametric Fingerboard Builder")
        self.setMinimumSize(1200, 760)
        self.resize(1540, 920)

        self.status_label = QLabel("Ready")
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
        for key in ["hand_span", "edge_rounding", "side_margin", "top_margin", "center_bulk", "edge_depth", "cord_hole_diameter"]:
            entry = QLineEdit()
            self.global_entries[key] = entry
            global_form.addRow(QLabel(key), entry)
        controls_layout.addWidget(global_group)

        # Advanced parameters (collapsible)
        self.advanced_group = QGroupBox("Advanced")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        self.advanced_group.toggled.connect(self._toggle_advanced_section)
        advanced_form = QFormLayout(self.advanced_group)
        for key in ["bottom_layer_thickness", "side_chamfer", "top_bottom_chamfer"]:
            entry = QLineEdit()
            self.advanced_entries[key] = entry
            advanced_form.addRow(QLabel(key), entry)
        controls_layout.addWidget(self.advanced_group)

        # Hand parameters
        hands_group = QGroupBox("Hand Parameters")
        hands_layout = QHBoxLayout(hands_group)
        right_group = QGroupBox("Right Hand")
        right_form = QFormLayout(right_group)
        for key in ["index_middle", "middle_ring", "ring_pinky"]:
            entry = QLineEdit()
            self.right_entries[key] = entry
            right_form.addRow(QLabel(key), entry)
        left_group = QGroupBox("Left Hand")
        left_form = QFormLayout(left_group)
        for key in ["index_middle", "middle_ring", "ring_pinky"]:
            entry = QLineEdit()
            self.left_entries[key] = entry
            left_form.addRow(QLabel(key), entry)
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
        controls_layout.addWidget(actions_widget)
        controls_layout.addStretch(1)

        main_layout.addWidget(controls_scroll, 0)

        # 3D Preview (right)
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        self.gl_view = gl.GLViewWidget()
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
            "hand_span": "68",
            "edge_rounding": "2.5",
            "side_margin": "8",
            "top_margin": "8",
            "center_bulk": "10",
            "edge_depth": "20",
            "cord_hole_diameter": "8",
        }
        advanced_defaults = {
            "bottom_layer_thickness": "5.0",
            "side_chamfer": "5.0",
            "top_bottom_chamfer": "2.0",
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
        self._schedule_preview()

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
                raise ValueError(f"top_margin must be >= min_side_margin ({min_val})")
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
        )

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
        base_color = np.array([0.27, 0.57, 0.90])
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
        self.gl_view.setCameraPosition(pos=QtGui.QVector3D(center[0], center[1], center[2] + size * 1.5), distance=size * 2)
        self.gl_view.opts['center'] = QtGui.QVector3D(*center)

    def _render_error_preview(self, message: str) -> None:
        for item in self.gl_view.items[:]:
            self.gl_view.removeItem(item)
        error_label = QLabel(f"Invalid parameters:\n{message}")
        error_label.setStyleSheet("color: #8a1f1f; background: #fbeaea; font-size: 14px;")
        self.status_label.setText(f"Preview failed: {message}")

    def on_preview(self, show_dialog: bool = True) -> None:
        try:
            params = self._collect_params()
            prepared = _prepare_fingerboard(params)
            shape, warning = build_fingerboard(params, prepared=prepared)
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
            if warning:
                msg += f" | {warning}"
                import re
                z_match = re.search(r"side_chamfer[^\n]*Clamped to ([0-9.]+) mm", warning)
                if z_match:
                    clamped_val = z_match.group(1)
                    entry = self.advanced_entries.get("side_chamfer")
                    if entry:
                        entry.setText(clamped_val)
                tb_match = re.search(r"top/bottom chamfer[^\n]*Clamped to ([0-9.]+) mm", warning)
                if tb_match:
                    clamped_val = tb_match.group(1)
                    entry = self.advanced_entries.get("top_bottom_chamfer")
                    if entry:
                        entry.setText(clamped_val)
                self.status_label.setText(msg)
                if show_dialog:
                    QMessageBox.warning(self, "Chamfer Clamped", warning)
            else:
                self.status_label.setText(msg)
        except Exception as exc:
            self.status_label.setText(f"Preview failed: {exc}")
            self._render_error_preview(str(exc))
            if show_dialog:
                QMessageBox.critical(self, "Preview failed", str(exc))

    def on_export(self) -> None:
        try:
            params = self._collect_params()
            prepared = _prepare_fingerboard(params)
            # Swap length and width for output
            board_width, board_length, board_height = (
                prepared.board_length,
                prepared.board_width,
                prepared.board_height,
            )
            path, _ = QFileDialog.getSaveFileName(self, "Save STL", "", "STL mesh (*.stl)")
            if not path:
                self.status_label.setText("Export cancelled")
                return
            shape = build_fingerboard(params, prepared=prepared)
            output = export_stl(params, path, shape=shape, prepared=prepared)
            self.status_label.setText(
                f"STL exported | L={board_length:.1f} mm, W={board_width:.1f} mm, H={board_height:.1f} mm | {output}"
            )
        except Exception as exc:
            self.status_label.setText(f"Export failed: {exc}")
            QMessageBox.critical(self, "Export failed", str(exc))


def run_app():
    app = QApplication([])
    window = FingerboardGUI()
    window.show()
    app.exec()
