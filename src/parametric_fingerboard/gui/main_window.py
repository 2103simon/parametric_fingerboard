
"""
Graphical user interface for the Parametric Fingerboard Builder application.

Implements the main window, parameter entry forms, preview rendering, and STL export functionality using Tkinter and Matplotlib.
"""

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
    SideParameters,
    build_fingerboard,
    _prepare_fingerboard,
    export_stl,
)


class FingerboardGUI:
    """
    Main GUI class for the Parametric Fingerboard Builder.

    Handles layout, parameter entry, preview rendering, and STL export.
    Provides all user interaction and visualization for the application.
    """
    def __init__(self, root: tk.Tk) -> None:
        """
        Initializes the main window, sets up the layout, and populates default values.

        Args:
            root (tk.Tk): The root Tkinter window.
        """
        self.root = root
        self.root.title("Parametric Fingerboard Builder")
        self.root.geometry("1540x920")
        self.root.minsize(1200, 760)

        self.status_var = tk.StringVar(value="Ready")
        self.global_entries: dict[str, ttk.Entry] = {}
        self.left_entries: dict[str, ttk.Entry] = {}
        self.right_entries: dict[str, ttk.Entry] = {}
        self.advanced_entries: dict[str, ttk.Entry] = {}
        self._preview_after_id: str | None = None

        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.ax = self.figure.add_subplot(111, projection="3d")

        self._build_layout()
        self._set_defaults()

    def _build_layout(self) -> None:
        """
        Constructs and packs all main window widgets, including parameter forms, preview area, and action buttons.
        Sets up scrollable controls, preview canvas, and binds mouse/keyboard events.
        """
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
        self._add_form_row(global_frame, "hand_span", self.global_entries)
        self._add_form_row(global_frame, "edge_rounding", self.global_entries)
        self._add_form_row(global_frame, "side_margin", self.global_entries)
        self._add_form_row(global_frame, "top_margin", self.global_entries)
        self._add_form_row(global_frame, "center_bulk", self.global_entries)
        self._add_form_row(global_frame, "edge_depth", self.global_entries)
        self._add_form_row(global_frame, "cord_hole_diameter", self.global_entries)

        # Advanced section (collapsible)
        self.advanced_visible = tk.BooleanVar(value=False)
        advanced_frame = ttk.LabelFrame(controls, text="Advanced", padding=8)
        advanced_frame.pack(fill=tk.X, pady=(0, 10))
        advanced_toggle = ttk.Checkbutton(
            advanced_frame,
            text="Show Advanced Settings",
            variable=self.advanced_visible,
            command=self._toggle_advanced_section,
            style="Toolbutton"
        )
        advanced_toggle.pack(anchor="w")
        self.advanced_section = ttk.Frame(advanced_frame)
        self.advanced_section.pack(fill=tk.X, pady=(8, 0))
        self._add_form_row(self.advanced_section, "bottom_layer_thickness", self.advanced_entries)
        self._add_form_row(self.advanced_section, "side_chamfer", self.advanced_entries)
        self._add_form_row(self.advanced_section, "top_bottom_chamfer", self.advanced_entries)
        self._toggle_advanced_section()

        # --- Move these back to _build_layout ---
        hands_frame = ttk.Frame(controls)
        hands_frame.pack(fill=tk.BOTH, expand=True)

        right_frame = ttk.LabelFrame(hands_frame, text="Right Hand", padding=8)
        right_frame.pack(fill=tk.X, pady=(0, 10))
        self._add_side_rows(right_frame, self.right_entries)

        left_frame = ttk.LabelFrame(hands_frame, text="Left Hand", padding=8)
        left_frame.pack(fill=tk.X)
        self._add_side_rows(left_frame, self.left_entries)

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

    def _toggle_advanced_section(self):
        """
        Shows or hides the advanced parameter section and re-binds preview events.
        Updates the preview event bindings to reflect the current UI state.
        """
        if self.advanced_visible.get():
            self.advanced_section.pack(fill=tk.X, pady=(8, 0))
        else:
            self.advanced_section.pack_forget()

        self._bind_auto_preview_events()

    def _add_side_rows(self, frame: ttk.LabelFrame, entry_map: dict[str, ttk.Entry]) -> None:
        """
        Adds entry rows for finger deltas (index-middle, middle-ring, ring-pinky) to the given frame.

        Args:
            frame (ttk.LabelFrame): The parent frame for the entry rows.
            entry_map (dict[str, ttk.Entry]): The entry map to populate.
        """
        self._add_form_row(frame, "index_middle", entry_map)
        self._add_form_row(frame, "middle_ring", entry_map)
        self._add_form_row(frame, "ring_pinky", entry_map)

    def _add_form_row(self, frame: ttk.LabelFrame | ttk.Frame, key: str, entry_map: dict[str, ttk.Entry]) -> None:
        """
        Adds a labeled entry row for a single parameter to the given frame and entry map.

        Args:
            frame (ttk.LabelFrame | ttk.Frame): The parent frame for the entry row.
            key (str): The parameter key.
            entry_map (dict[str, ttk.Entry]): The entry map to update.
        """
        row = ttk.Frame(frame)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=key, width=20).pack(side=tk.LEFT)
        entry = ttk.Entry(row, width=10)
        entry.pack(side=tk.RIGHT)
        entry_map[key] = entry

    def _bind_auto_preview_events(self) -> None:
        """
        Binds auto-preview scheduling to all parameter entry widgets for key, focus, and clipboard events.
        Ensures that any user input triggers a preview update after a debounce delay.
        """
        all_entries = [
            *self.global_entries.values(),
            *self.left_entries.values(),
            *self.right_entries.values(),
            *self.advanced_entries.values(),
        ]
        for entry in all_entries:
            entry.bind("<KeyRelease>", self._schedule_preview)
            entry.bind("<FocusOut>", self._schedule_preview)
            entry.bind("<<Paste>>", self._schedule_preview)
            entry.bind("<<Cut>>", self._schedule_preview)

    def _schedule_preview(self, _event: tk.Event | None = None) -> None:
        """
        Schedules a delayed preview update after user input, debouncing rapid changes.

        Args:
            _event (tk.Event | None, optional): Event argument for Tkinter compatibility (unused).
        """
        if self._preview_after_id is not None:
            self.root.after_cancel(self._preview_after_id)
        self._preview_after_id = self.root.after(800, self._run_scheduled_preview)

    def _run_scheduled_preview(self) -> None:
        """
        Executes the preview update after the debounce delay.
        Calls on_preview to update the 3D preview.
        """
        self._preview_after_id = None
        self.on_preview(show_dialog=False)

    def _set_defaults(self) -> None:
        """
        Populates all parameter entry fields with default values and triggers the initial preview.
        Sets minimum allowed values for margins.
        """
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
            self.global_entries[k].insert(0, v)
        for k, v in advanced_defaults.items():
            self.advanced_entries[k].insert(0, v)

        side_defaults = {
            "index_middle": "0",
            "middle_ring": "0",
            "ring_pinky": "0",
        }
        for values in (self.left_entries, self.right_entries):
            for k, v in side_defaults.items():
                values[k].insert(0, v)

        self._schedule_preview()

    def _float_value(self, entry_map: dict[str, ttk.Entry], key: str) -> float:
        """
        Retrieves and validates a float value from an entry widget, enforcing minimum margins if relevant.

        Args:
            entry_map (dict[str, ttk.Entry]): The entry map containing the widget.
            key (str): The parameter key.

        Returns:
            float: The validated float value.

        Raises:
            ValueError: If the value is below the allowed minimum for side_margin or top_margin.
        """
        value = float(entry_map[key].get().strip())
        # Enforce min_side_margin and min_top_margin if relevant
        if key == "side_margin":
            min_val = getattr(self, "min_side_margin", 0.0)
            if value < min_val:
                entry_map[key].delete(0, tk.END)
                entry_map[key].insert(0, str(min_val))
                raise ValueError(f"side_margin must be >= min_side_margin ({min_val})")
            return value
        if key == "top_margin":
            min_val = getattr(self, "min_top_margin", 0.0)
            if value < min_val:
                entry_map[key].delete(0, tk.END)
                entry_map[key].insert(0, str(min_val))
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
        )

    def _render_preview(self, stl_path: Path) -> None:
        """
        Loads the STL mesh and renders a 3D preview in the Matplotlib canvas.

        Args:
            stl_path (Path): Path to the STL file to render.
        """
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
        poly = Poly3DCollection(triangles, linewidths=0.0, antialiased=False)
        poly.set_facecolor(face_colors)
        poly.set_edgecolor("none")
        self.ax.add_collection3d(poly)

        bounds = mesh.bounds
        mins = bounds[0]
        maxs = bounds[1]

        self.ax.set_xlim(mins[0], maxs[0])
        self.ax.set_ylim(mins[1], maxs[1])
        self.ax.set_zlim(mins[2], maxs[2])
        self.ax.set_box_aspect((maxs - mins).tolist())
        self.ax.set_title("Preview")
        self.ax.set_proj_type("ortho")
        self.ax.view_init(elev=22, azim=-52)
        self.ax.grid(False)
        self.ax.set_facecolor((0.96, 0.97, 0.99, 1.0))
        self.ax.set_axis_off()
        self.canvas.draw_idle()

    def _render_error_preview(self, message: str) -> None:
        """
        Displays an error message in the preview area if parameter validation fails.

        Args:
            message (str): The error message to display.
        """
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
        """
        Generates and displays a preview of the fingerboard using current parameters.
        Shows warnings or errors as needed.

        Args:
            show_dialog (bool, optional): Whether to show warning/error dialogs. Defaults to True.
        """
        try:
            params = self._collect_params()
            prepared = _prepare_fingerboard(params)
            shape, warning = build_fingerboard(params, prepared=prepared)
            board_length, board_width, board_height = (
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
                # Update side_chamfer entry if clamped
                z_match = re.search(r"side_chamfer[^\n]*Clamped to ([0-9.]+) mm", warning)
                if z_match:
                    clamped_val = z_match.group(1)
                    entry = self.advanced_entries.get("side_chamfer")
                    if entry:
                        entry.delete(0, tk.END)
                        entry.insert(0, clamped_val)
                # Update top_bottom_chamfer entry if clamped
                tb_match = re.search(r"top/bottom chamfer[^\n]*Clamped to ([0-9.]+) mm", warning)
                if tb_match:
                    clamped_val = tb_match.group(1)
                    entry = self.advanced_entries.get("top_bottom_chamfer")
                    if entry:
                        entry.delete(0, tk.END)
                        entry.insert(0, clamped_val)
                self.status_var.set(msg)
                if show_dialog:
                    messagebox.showwarning("Chamfer Clamped", warning)
            else:
                self.status_var.set(msg)
        except Exception as exc:
            self.status_var.set(f"Preview failed: {exc}")
            self._render_error_preview(str(exc))
            if show_dialog:
                messagebox.showerror("Preview failed", str(exc))

    def on_export(self) -> None:
        """
        Exports the current fingerboard model to an STL file, prompting the user for a save location.
        Shows errors if export fails or is cancelled.
        Updates the status bar with the result.
        """
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
    """
    Launches the Parametric Fingerboard Builder GUI application.
    Sets up the Tkinter root window and starts the main event loop.
    """
    root = tk.Tk()
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    FingerboardGUI(root)
    root.mainloop()
