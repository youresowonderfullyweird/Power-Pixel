"""
gui.py

A simple desktop GUI (Tkinter — ships with Python, no extra installs) for
the drone-location 3D model pipeline. Runs locally because the pipeline
needs to launch your local Blender executable and read/write local files.

Lets you either:
  (a) pick a drone video + its .SRT telemetry sidecar (video is optional —
      the .SRT alone is enough), or
  (b) type a manual lat/lon directly

Launch it with:

    python gui.py
"""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from main import run_pipeline


class DroneModelApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Drone Location 3D Model Builder (Blosm + ArcGIS)")
        self.geometry("720x720")
        self.resizable(True, True)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker_thread = None

        self._build_widgets()
        self._poll_log_queue()

    # ------------------------------------------------------------------ UI

    def _build_widgets(self):
        pad = {"padx": 8, "pady": 4}

        # --- Location source ---
        loc_frame = ttk.LabelFrame(self, text="1. Location source")
        loc_frame.pack(fill="x", **pad)

        self.location_mode = tk.StringVar(value="metadata")
        ttk.Radiobutton(
            loc_frame, text="Use drone video / SRT metadata", value="metadata",
            variable=self.location_mode, command=self._update_location_mode,
        ).grid(row=0, column=0, columnspan=3, sticky="w", **pad)
        ttk.Radiobutton(
            loc_frame, text="Enter latitude / longitude manually", value="manual",
            variable=self.location_mode, command=self._update_location_mode,
        ).grid(row=1, column=0, columnspan=3, sticky="w", **pad)

        # video / srt / gpx pickers
        self.video_path = tk.StringVar()
        self.srt_path = tk.StringVar()
        self.gpx_path = tk.StringVar()

        self.video_row = self._file_row(loc_frame, 2, "Drone video (optional):", self.video_path,
                                         [("Video files", "*.mp4 *.mov *.MP4 *.MOV"), ("All files", "*.*")])
        self.srt_row = self._file_row(loc_frame, 3, "SRT telemetry file:", self.srt_path,
                                       [("SRT files", "*.srt *.SRT"), ("All files", "*.*")])
        self.gpx_row = self._file_row(loc_frame, 4, "GPX flight log (optional):", self.gpx_path,
                                       [("GPX files", "*.gpx"), ("All files", "*.*")])

        # manual lat/lon
        self.manual_lat = tk.StringVar()
        self.manual_lon = tk.StringVar()
        self.manual_row_widgets = []
        lbl = ttk.Label(loc_frame, text="Latitude, Longitude:")
        lbl.grid(row=5, column=0, sticky="w", **pad)
        lat_entry = ttk.Entry(loc_frame, textvariable=self.manual_lat, width=15)
        lat_entry.grid(row=5, column=1, sticky="w", **pad)
        lon_entry = ttk.Entry(loc_frame, textvariable=self.manual_lon, width=15)
        lon_entry.grid(row=5, column=2, sticky="w", **pad)
        self.manual_row_widgets = [lbl, lat_entry, lon_entry]

        loc_frame.columnconfigure(1, weight=1)
        self._update_location_mode()

        # --- Area + ArcGIS ---
        area_frame = ttk.LabelFrame(self, text="2. Area & ArcGIS")
        area_frame.pack(fill="x", **pad)

        ttk.Label(area_frame, text="Area side length (km):").grid(row=0, column=0, sticky="w", **pad)
        self.side_km = tk.StringVar(value="1.5")
        ttk.Entry(area_frame, textvariable=self.side_km, width=10).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(area_frame, text="ArcGIS access token:").grid(row=1, column=0, sticky="w", **pad)
        self.arcgis_token = tk.StringVar()
        ttk.Entry(area_frame, textvariable=self.arcgis_token, width=50, show="*").grid(
            row=1, column=1, columnspan=2, sticky="we", **pad
        )
        area_frame.columnconfigure(1, weight=1)

        # --- Import options ---
        opts_frame = ttk.LabelFrame(self, text="3. What to import")
        opts_frame.pack(fill="x", **pad)

        self.import_buildings = tk.BooleanVar(value=True)
        self.import_terrain = tk.BooleanVar(value=True)
        self.import_satellite = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts_frame, text="Buildings (OSM)", variable=self.import_buildings).grid(
            row=0, column=0, sticky="w", **pad
        )
        ttk.Checkbutton(opts_frame, text="Terrain", variable=self.import_terrain).grid(
            row=0, column=1, sticky="w", **pad
        )
        ttk.Checkbutton(opts_frame, text="ArcGIS satellite overlay", variable=self.import_satellite).grid(
            row=0, column=2, sticky="w", **pad
        )

        # --- Output ---
        out_frame = ttk.LabelFrame(self, text="4. Output")
        out_frame.pack(fill="x", **pad)

        ttk.Label(out_frame, text="Blender executable:").grid(row=0, column=0, sticky="w", **pad)
        self.blender_exe = tk.StringVar(value="blender")
        ttk.Entry(out_frame, textvariable=self.blender_exe, width=45).grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(out_frame, text="Browse...", command=self._pick_blender_exe).grid(row=0, column=2, **pad)

        ttk.Label(out_frame, text="Output base path (no extension):").grid(row=1, column=0, sticky="w", **pad)
        self.out_base = tk.StringVar(value=str(Path.cwd() / "model"))
        ttk.Entry(out_frame, textvariable=self.out_base, width=45).grid(row=1, column=1, sticky="we", **pad)
        ttk.Button(out_frame, text="Browse...", command=self._pick_out_base).grid(row=1, column=2, **pad)

        fmt_row = ttk.Frame(out_frame)
        fmt_row.grid(row=2, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(fmt_row, text="Export formats:").pack(side="left")
        self.fmt_glb = tk.BooleanVar(value=True)
        self.fmt_ply = tk.BooleanVar(value=True)
        self.fmt_blend = tk.BooleanVar(value=True)
        ttk.Checkbutton(fmt_row, text=".glb", variable=self.fmt_glb).pack(side="left", padx=6)
        ttk.Checkbutton(fmt_row, text=".ply", variable=self.fmt_ply).pack(side="left", padx=6)
        ttk.Checkbutton(fmt_row, text=".blend", variable=self.fmt_blend).pack(side="left", padx=6)

        out_frame.columnconfigure(1, weight=1)

        # --- Run ---
        run_frame = ttk.Frame(self)
        run_frame.pack(fill="x", **pad)
        self.run_button = ttk.Button(run_frame, text="Build 3D Model", command=self._on_run)
        self.run_button.pack(side="left", **pad)
        self.progress = ttk.Progressbar(run_frame, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True, **pad)

        # --- Log ---
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=16, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _file_row(self, parent, row, label, var, filetypes):
        pad = {"padx": 8, "pady": 4}
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", **pad)
        entry = ttk.Entry(parent, textvariable=var, width=45)
        entry.grid(row=row, column=1, sticky="we", **pad)
        button = ttk.Button(parent, text="Browse...", command=lambda: self._pick_file(var, filetypes))
        button.grid(row=row, column=2, **pad)
        return (entry, button)

    def _pick_file(self, var, filetypes):
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            var.set(path)

    def _pick_blender_exe(self):
        path = filedialog.askopenfilename(title="Locate blender.exe / blender binary")
        if path:
            self.blender_exe.set(path)

    def _pick_out_base(self):
        path = filedialog.asksaveasfilename(title="Choose output base name (extension ignored)")
        if path:
            self.out_base.set(str(Path(path).with_suffix("")))

    def _update_location_mode(self):
        is_metadata = self.location_mode.get() == "metadata"
        for widgets in (self.video_row, self.srt_row, self.gpx_row):
            for w in widgets:
                w.configure(state="normal" if is_metadata else "disabled")
        for w in self.manual_row_widgets:
            w.configure(state="disabled" if is_metadata else "normal")

    # -------------------------------------------------------------- logic

    def _log(self, message: str):
        # Called from the worker thread — push to a queue the UI thread drains.
        self.log_queue.put(message)

    def _poll_log_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                if message == "__DONE__":
                    continue
                self.log_text.configure(state="normal")
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _on_run(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Busy", "A build is already running.")
            return

        try:
            side_km = float(self.side_km.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Area side length must be a number.")
            return

        if not self.arcgis_token.get().strip():
            messagebox.showerror("Missing token", "Please enter your ArcGIS access token.")
            return

        formats = [f for f, v in [("glb", self.fmt_glb), ("ply", self.fmt_ply), ("blend", self.fmt_blend)]
                   if v.get()]
        if not formats:
            messagebox.showerror("No formats selected", "Pick at least one export format.")
            return

        kwargs = dict(
            side_km=side_km,
            arcgis_token=self.arcgis_token.get().strip(),
            blender_exe=self.blender_exe.get().strip() or "blender",
            out_base=self.out_base.get().strip() or "model",
            formats=formats,
            import_buildings=self.import_buildings.get(),
            import_terrain=self.import_terrain.get(),
            import_satellite=self.import_satellite.get(),
            log=self._log,
        )

        if self.location_mode.get() == "manual":
            try:
                lat = float(self.manual_lat.get())
                lon = float(self.manual_lon.get())
            except ValueError:
                messagebox.showerror("Invalid input", "Latitude/longitude must be numbers.")
                return
            kwargs["manual_latlon"] = (lat, lon)
        else:
            video = self.video_path.get().strip() or None
            srt = self.srt_path.get().strip() or None
            gpx = self.gpx_path.get().strip() or None
            if not any([video, srt, gpx]):
                messagebox.showerror(
                    "Missing location source",
                    "Provide a video, an SRT file, or a GPX file — or switch to manual lat/lon.",
                )
                return
            kwargs.update(video=video, srt=srt, gpx=gpx)

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        self.run_button.configure(state="disabled")
        self.progress.start(12)

        def worker():
            try:
                run_pipeline(**kwargs)
                self._log("\n✔ Build finished successfully.")
            except Exception as e:
                self._log(f"\n✘ Build failed: {e}")
            finally:
                self.log_queue.put("__DONE__")

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()
        self._watch_done()

    def _watch_done(self):
        # Re-enable the Run button once the worker signals completion.
        if self.worker_thread and self.worker_thread.is_alive():
            self.after(200, self._watch_done)
        else:
            self.progress.stop()
            self.run_button.configure(state="normal")


if __name__ == "__main__":
    app = DroneModelApp()
    app.mainloop()
