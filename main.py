import json
import os
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "download_dir": str(Path.home() / "Downloads"),
    "quality": "Best",
}

QUALITY_OPTIONS = {
    "Best": [],
    "1080p": ["-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"],
    "720p": ["-f", "bestvideo[height<=720]+bestaudio/best[height<=720]"],
    "480p": ["-f", "bestvideo[height<=480]+bestaudio/best[height<=480]"],
    "Audio Only": ["-x", "--audio-format", "mp3"],
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            for key, value in DEFAULT_CONFIG.items():
                config.setdefault(key, value)
            return config
        except (json.JSONDecodeError, IOError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except IOError:
        pass


class YtDlpGui:
    def __init__(self, root):
        self.root = root
        self.root.title("yt-dlp GUI")
        self.root.minsize(600, 500)
        self.root.resizable(True, True)

        self.config = load_config()
        self.downloading = False
        self.process = None
        self.output_queue = queue.Queue()

        self._build_ui()
        self._check_ytdlp()

    def _build_ui(self):
        padding = {"padx": 10, "pady": 5}
        self.root.columnconfigure(0, weight=1)

        # --- URL Section ---
        url_frame = ttk.LabelFrame(self.root, text="Video or Playlist URL", padding=10)
        url_frame.grid(row=0, column=0, sticky="ew", **padding)
        url_frame.columnconfigure(0, weight=1)

        self.url_entry = ttk.Entry(url_frame, font=("Segoe UI", 11))
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        paste_btn = ttk.Button(url_frame, text="Paste", width=8, command=self._paste_url)
        paste_btn.grid(row=0, column=1)

        # --- Download Directory Section ---
        dir_frame = ttk.LabelFrame(self.root, text="Download Directory", padding=10)
        dir_frame.grid(row=1, column=0, sticky="ew", **padding)
        dir_frame.columnconfigure(0, weight=1)

        self.dir_var = tk.StringVar(value=self.config["download_dir"])
        dir_entry = ttk.Entry(dir_frame, textvariable=self.dir_var, state="readonly", font=("Segoe UI", 10))
        dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        browse_btn = ttk.Button(dir_frame, text="Browse", width=8, command=self._browse_dir)
        browse_btn.grid(row=0, column=1)

        # --- Options Section ---
        options_frame = ttk.LabelFrame(self.root, text="Options", padding=10)
        options_frame.grid(row=2, column=0, sticky="ew", **padding)

        ttk.Label(options_frame, text="Quality:").grid(row=0, column=0, padx=(0, 5))
        self.quality_var = tk.StringVar(value=self.config.get("quality", "Best"))
        quality_combo = ttk.Combobox(
            options_frame,
            textvariable=self.quality_var,
            values=list(QUALITY_OPTIONS.keys()),
            state="readonly",
            width=15,
        )
        quality_combo.grid(row=0, column=1)

        # --- Download Button ---
        self.download_btn = ttk.Button(
            self.root, text="Download", command=self._start_download
        )
        self.download_btn.grid(row=3, column=0, sticky="ew", **padding)

        style = ttk.Style()
        style.configure("TButton", font=("Segoe UI", 11))

        # --- Status Section ---
        status_frame = ttk.LabelFrame(self.root, text="Status", padding=10)
        status_frame.grid(row=4, column=0, sticky="nsew", **padding)
        status_frame.columnconfigure(0, weight=1)
        status_frame.rowconfigure(1, weight=1)
        self.root.rowconfigure(4, weight=1)

        self.status_var = tk.StringVar(value="Idle")
        status_label = ttk.Label(status_frame, textvariable=self.status_var, font=("Segoe UI", 10, "bold"))
        status_label.grid(row=0, column=0, sticky="w")

        self.log_text = tk.Text(status_frame, height=10, wrap="word", state="disabled", font=("Consolas", 9))
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(5, 0))

        scrollbar = ttk.Scrollbar(status_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(5, 0))
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _check_ytdlp(self):
        if not shutil.which("yt-dlp"):
            self.status_var.set("Warning: yt-dlp not found in PATH")
            self._log("yt-dlp is not installed or not in your system PATH.\n")
            self._log("Install it with: pip install yt-dlp\n")
            self._log("Or download from: https://github.com/yt-dlp/yt-dlp#installation\n")

    def _paste_url(self):
        try:
            clipboard = self.root.clipboard_get()
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, clipboard.strip())
        except tk.TclError:
            pass

    def _browse_dir(self):
        directory = filedialog.askdirectory(initialdir=self.dir_var.get())
        if directory:
            self.dir_var.set(directory)
            self.config["download_dir"] = directory
            save_config(self.config)

    def _log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _start_download(self):
        url = self.url_entry.get().strip()
        if not url:
            self.status_var.set("Error: No URL provided")
            return

        download_dir = self.dir_var.get()
        if not os.path.isdir(download_dir):
            self.status_var.set("Error: Download directory does not exist")
            return

        self.config["quality"] = self.quality_var.get()
        save_config(self.config)

        self._clear_log()
        self.downloading = True
        self.download_btn.configure(state="disabled")
        self.status_var.set("Downloading...")

        cmd = ["yt-dlp", "--newline", "-o", os.path.join(download_dir, "%(title)s.%(ext)s")]
        quality = self.quality_var.get()
        cmd.extend(QUALITY_OPTIONS.get(quality, []))
        cmd.append(url)

        thread = threading.Thread(target=self._run_download, args=(cmd,), daemon=True)
        thread.start()
        self._poll_output()

    def _run_download(self, cmd):
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            for line in self.process.stdout:
                self.output_queue.put(line)
            self.process.wait()
            self.output_queue.put(("__DONE__", self.process.returncode))
        except FileNotFoundError:
            self.output_queue.put("Error: yt-dlp not found. Please install it first.\n")
            self.output_queue.put(("__DONE__", 1))
        except Exception as e:
            self.output_queue.put(f"Error: {e}\n")
            self.output_queue.put(("__DONE__", 1))

    def _poll_output(self):
        while True:
            try:
                item = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if isinstance(item, tuple) and item[0] == "__DONE__":
                return_code = item[1]
                self.downloading = False
                self.process = None
                self.download_btn.configure(state="normal")
                if return_code == 0:
                    self.status_var.set("Complete")
                    self._log("\nDownload finished successfully.\n")
                else:
                    self.status_var.set("Error")
                    self._log(f"\nDownload failed (exit code {return_code}).\n")
                return
            else:
                self._log(item)

        if self.downloading:
            self.root.after(100, self._poll_output)


def main():
    root = tk.Tk()
    YtDlpGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
