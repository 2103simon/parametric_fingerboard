from __future__ import annotations

import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
import trimesh
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from parametric_fingerboard.model import (
    FingerboardParameters,
    PreparedFingerboard,
    SideParameters,
    build_fingerboard,
    _prepare_fingerboard,
    derive_dimensions,
    export_stl,
)


class FingerboardGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Parametric Fingerboard Builder")
        self.root.geometry("1540x920")
        self.root.minsize(1200, 760)

        self.status_var = tk.StringVar(value="Ready")
        self.global_entries: dict[str, ttk.Entry] = {}
        self.left_entries: dict[str, ttk.Entry] = {}
        self.right_entries: dict[str, ttk.Entry] = {}
        self._preview_after_id: str | None = None

        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.ax = self.figure.add_subplot(111, projection="3d")

        self._build_layout()
        self._set_defaults()

    def _build_layout(self) -> None:
        shell = ttk.Frame(self.root, padding=12)
        shell.pack(fill=tk.BOTH, expand=True)

        controls_outer = ttk.Frame(shell, width=430)
        controls_outer.pack(side=tk.LEFT, fill=tk.Y)
        controls_outer.pack_propagate(False)

        controls_canvas = tk.Canvas(controls_outer, highlightthickness=0)
        controls_scroll = ttk.Scrollbar(controls_outer, orient=tk.VERTICAL, command=controls_canvas.yview)
        controls_canvas.configure(yscrollcommand=controls_scroll.set)

        controls_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        controls_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        controls = ttk.Frame(controls_canvas)
        controls_window = controls_canvas.create_window((0, 0), window=controls, anchor="nw")

        controls.bind(
            "<Configure>",
            lambda _event: controls_canvas.configure(scrollregion=controls_canvas.bbox("all")),
        )
        controls_canvas.bind(
            "<Configure>",
            lambda event: controls_canvas.itemconfigure(controls_window, width=event.width),
        )

        preview = ttk.Frame(shell)
        preview.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(12, 0))

        global_frame = ttk.LabelFrame(controls, text="Global Parameters", padding=8)
        global_frame.pack(fill=tk.X, pady=(0, 10))
        self._add_form_row(global_frame, "board_width_scale", self.global_entries)
        self._add_form_row(global_frame, "x_margin", self.global_entries)
        self._add_form_row(global_frame, "y_margin", self.global_entries)
        self._add_form_row(global_frame, "outer_wall_thickness", self.global_entries)
        self._add_form_row(global_frame, "fixed_x_space", self.global_entries)
        self._add_form_row(global_frame, "center_bulk", self.global_entries)
        self._add_form_row(global_frame, "height_margin", self.global_entries)
        self._add_form_row(global_frame, "min_board_length", self.global_entries)
        self._add_form_row(global_frame, "min_board_width", self.global_entries)
        self._add_form_row(global_frame, "min_board_height", self.global_entries)
        self._add_form_row(global_frame, "cord_hole_diameter", self.global_entries)

        hands_frame = ttk.Frame(controls)
        hands_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.LabelFrame(hands_frame, text="Left Hand", padding=8)
        left_frame.pack(fill=tk.X, pady=(0, 10))
        self._add_side_rows(left_frame, self.left_entries)

        right_frame = ttk.LabelFrame(hands_frame, text="Right Hand", padding=8)
        right_frame.pack(fill=tk.X)
        self._add_side_rows(right_frame, self.right_entries)

        actions = ttk.Frame(controls)
        actions.pack(fill=tk.X, pady=(12, 0))

        ttk.Button(actions, text="Export STL", command=self.on_export).pack(fill=tk.X)

        ttk.Label(controls, textvariable=self.status_var, wraplength=360).pack(fill=tk.X, pady=(12, 0))

        controls.bind_all(
            "<MouseWheel>",
            lambda event: controls_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"),
        )
        controls.bind_all("<Button-4>", lambda _event: controls_canvas.yview_scroll(-1, "units"))
        controls.bind_all("<Button-5>", lambda _event: controls_canvas.yview_scroll(1, "units"))

        canvas = FigureCanvasTkAgg(self.figure, master=preview)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas = canvas

        self._bind_auto_preview_events()

    def _add_side_rows(self, frame: ttk.LabelFrame, entry_map: dict[str, ttk.Entry]) -> None:
        self._add_form_row(frame, "edge_depth", entry_map)
        self._add_form_row(frame, "hand_span", entry_map)
        self._add_form_row(frame, "index_middle", entry_map)
        self._add_form_row(frame, "middle_ring", entry_map)
        self._add_form_row(frame, "ring_pinky", entry_map)
        self._add_form_row(frame, "edge_rounding", entry_map)

    def _add_form_row(self, frame: ttk.LabelFrame | ttk.Frame, key: str, entry_map: dict[str, ttk.Entry]) -> None:
        row = ttk.Frame(frame)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=key, width=20).pack(side=tk.LEFT)
        entry = ttk.Entry(row, width=10)
        entry.pack(side=tk.RIGHT)
        entry_map[key] = entry

    def _bind_auto_preview_events(self) -> None:
        all_entries = [
            *self.global_entries.values(),
            *self.left_entries.values(),
            *self.right_entries.values(),
        ]
        for entry in all_entries:
            entry.bind("<KeyRelease>", self._schedule_preview)
            entry.bind("<FocusOut>", self._schedule_preview)
            entry.bind("<<Paste>>", self._schedule_preview)
            entry.bind("<<Cut>>", self._schedule_preview)

    def _schedule_preview(self, _event: tk.Event | None = None) -> None:
        if self._preview_after_id is not None:
            self.root.after_cancel(self._preview_after_id)
        self._preview_after_id = self.root.after(220, self._run_scheduled_preview)

    def _run_scheduled_preview(self) -> None:
        self._preview_after_id = None
        self.on_preview(show_dialog=False)

    def _set_defaults(self) -> None:
        defaults = {
            "board_width_scale": "1.0",
            "x_margin": "8",
            "y_margin": "6",
            "outer_wall_thickness": "10",
            "fixed_x_space": "10",
            "center_bulk": "10",
            "height_margin": "10",
            "min_board_length": "110",
            "min_board_width": "46",
            "min_board_height": "34",
            "cord_hole_diameter": "8",
        }
        for k, v in defaults.items():
            self.global_entries[k].insert(0, v)

        side_defaults = {
            "edge_depth": "20",
            "hand_span": "68",
            "index_middle": "0",
            "middle_ring": "0",
            "ring_pinky": "0",
            "edge_rounding": "2.5",
        }
        for values in (self.left_entries, self.right_entries):
            for k, v in side_defaults.items():
                values[k].insert(0, v)

        self._schedule_preview()

    def _float_value(self, entry_map: dict[str, ttk.Entry], key: str) -> float:
        return float(entry_map[key].get().strip())

    def _collect_params(self) -> FingerboardParameters:
        left = SideParameters(
            edge_depth=self._float_value(self.left_entries, "edge_depth"),
            hand_span=self._float_value(self.left_entries, "hand_span"),
            index_middle=self._float_value(self.left_entries, "index_middle"),
            middle_ring=self._float_value(self.left_entries, "middle_ring"),
            ring_pinky=self._float_value(self.left_entries, "ring_pinky"),
            edge_rounding=self._float_value(self.left_entries, "edge_rounding"),
        )

        right = SideParameters(
            edge_depth=self._float_value(self.right_entries, "edge_depth"),
            hand_span=self._float_value(self.right_entries, "hand_span"),
            index_middle=self._float_value(self.right_entries, "index_middle"),
            middle_ring=self._float_value(self.right_entries, "middle_ring"),
            ring_pinky=self._float_value(self.right_entries, "ring_pinky"),
            edge_rounding=self._float_value(self.right_entries, "edge_rounding"),
        )

        return FingerboardParameters(
            left=left,
            right=right,
            board_width_scale=self._float_value(self.global_entries, "board_width_scale"),
            x_margin=self._float_value(self.global_entries, "x_margin"),
            y_margin=self._float_value(self.global_entries, "y_margin"),
            outer_wall_thickness=self._float_value(self.global_entries, "outer_wall_thickness"),
            fixed_x_space=self._float_value(self.global_entries, "fixed_x_space"),
            center_bulk=self._float_value(self.global_entries, "center_bulk"),
            height_margin=self._float_value(self.global_entries, "height_margin"),
            min_board_length=self._float_value(self.global_entries, "min_board_length"),
            min_board_width=self._float_value(self.global_entries, "min_board_width"),
            min_board_height=self._float_value(self.global_entries, "min_board_height"),
            cord_hole_diameter=self._float_value(self.global_entries, "cord_hole_diameter"),
        )

    def _render_preview(self, stl_path: Path) -> None:
        mesh = trimesh.load_mesh(stl_path)
        triangles = mesh.vertices[mesh.faces]
        normals = mesh.face_normals

        light_dir = np.array([0.4, -0.55, 0.75], dtype=float)
        light_dir /= np.linalg.norm(light_dir)

        brightness = np.clip(normals @ light_dir, 0.0, 1.0)
        brightness = 0.22 + 0.78 * brightness

        base_color = np.array([0.27, 0.57, 0.90])
        face_colors = np.column_stack(
            [
                np.clip(base_color[0] * brightness, 0.0, 1.0),
                np.clip(base_color[1] * brightness, 0.0, 1.0),
                np.clip(base_color[2] * brightness, 0.0, 1.0),
                np.ones_like(brightness),
            ]
        )

        self.ax.clear()
        poly = Poly3DCollection(triangles, linewidths=0.08)
        poly.set_facecolor(face_colors)
        poly.set_edgecolor((0.10, 0.10, 0.10, 0.45))
        self.ax.add_collection3d(poly)

        bounds = mesh.bounds
        mins = bounds[0]
        maxs = bounds[1]

        self.ax.set_xlim(mins[0], maxs[0])
        self.ax.set_ylim(mins[1], maxs[1])
        self.ax.set_zlim(mins[2], maxs[2])
        self.ax.set_box_aspect((maxs - mins).tolist())
        self.ax.set_xlabel("X")
        self.ax.set_ylabel("Y")
        self.ax.set_zlabel("Z")
        self.ax.set_title("Preview")
        self.ax.view_init(elev=22, azim=-52)
        self.ax.grid(False)
        self.ax.set_facecolor((0.96, 0.97, 0.99, 1.0))
        self.canvas.draw_idle()

    def _render_error_preview(self, message: str) -> None:
        self.ax.clear()
        self.ax.set_title("Preview")
        self.ax.set_facecolor((0.985, 0.94, 0.94, 1.0))
        self.ax.grid(False)
        self.ax.text2D(
            0.03,
            0.95,
            f"Invalid parameters:\n{message}",
            transform=self.ax.transAxes,
            color="#8a1f1f",
            fontsize=10,
            verticalalignment="top",
        )
        self.canvas.draw_idle()

    def on_preview(self, show_dialog: bool = True) -> None:
        try:
            params = self._collect_params()
            prepared = _prepare_fingerboard(params)
            shape = build_fingerboard(params, prepared=prepared)
            board_length, board_width, board_height = (
                prepared.board_length,
                prepared.board_width,
                prepared.board_height,
            )
            with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            export_stl(params, tmp_path, shape=shape, prepared=prepared)
            self._render_preview(tmp_path)
            self.status_var.set(
                "Preview updated | "
                f"L={board_length:.1f} mm, W={board_width:.1f} mm, H={board_height:.1f} mm"
            )
        except Exception as exc:
            self.status_var.set(f"Preview failed: {exc}")
            self._render_error_preview(str(exc))
            if show_dialog:
                messagebox.showerror("Preview failed", str(exc))

    def on_export(self) -> None:
        try:
            params = self._collect_params()
            prepared = _prepare_fingerboard(params)
            board_length, board_width, board_height = (
                prepared.board_length,
                prepared.board_width,
                prepared.board_height,
            )
            path = filedialog.asksaveasfilename(
                title="Save STL",
                defaultextension=".stl",
                filetypes=[("STL mesh", "*.stl")],
            )
            if not path:
                self.status_var.set("Export cancelled")
                return

            shape = build_fingerboard(params, prepared=prepared)
            output = export_stl(params, path, shape=shape, prepared=prepared)
            self.status_var.set(
                "STL exported | "
                f"L={board_length:.1f} mm, W={board_width:.1f} mm, H={board_height:.1f} mm | {output}"
            )
        except Exception as exc:
            self.status_var.set(f"Export failed: {exc}")
            messagebox.showerror("Export failed", str(exc))


def run_app() -> None:
    root = tk.Tk()
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    FingerboardGUI(root)
    root.mainloop()
