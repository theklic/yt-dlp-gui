import json
import os
import queue
import re
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
    "Best": ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"],
    "1080p": ["-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]", "--merge-output-format", "mp4"],
    "720p": ["-f", "bestvideo[height<=720]+bestaudio/best[height<=720]", "--merge-output-format", "mp4"],
    "480p": ["-f", "bestvideo[height<=480]+bestaudio/best[height<=480]", "--merge-output-format", "mp4"],
    "Audio Only": ["-x", "--audio-format", "mp3"],
}

# Patterns for parsing yt-dlp output into user-friendly progress
RE_DOWNLOAD_ITEM = re.compile(r"\[download\]\s+Downloading item (\d+) of (\d+)")
RE_DOWNLOAD_DEST = re.compile(r"\[download\]\s+Destination:\s+(.+)")
RE_DOWNLOAD_PROGRESS = re.compile(r"\[download\]\s+([\d.]+)%\s+of\s+~?\s*([\d.]+\S+)\s+at\s+(.+?)\s+ETA\s+(.+)")
RE_DOWNLOAD_COMPLETE = re.compile(r"\[download\]\s+100%")
RE_ALREADY_DOWNLOADED = re.compile(r"\[download\]\s+(.+) has already been downloaded")
RE_EXTRACTING_URL = re.compile(r"\[youtube\]\s+Extracting URL:\s+(.+)")
RE_EXTRACTING = re.compile(r"\[youtube\]\s+(\S+):\s+Downloading webpage")
RE_MERGING = re.compile(r"\[Merger\]\s+Merging formats into")
RE_WARNING = re.compile(r"WARNING:\s*(.*)", re.IGNORECASE)
RE_ERROR = re.compile(r"ERROR:\s*(.*)", re.IGNORECASE)

# Known permanent failure reasons that should not be retried
PERMANENT_ERRORS = [
    "this video is not available",
    "private video",
    "video is unavailable",
    "this video has been removed",
    "account associated with this video has been terminated",
    "this video is no longer available",
    "join this channel to get access",
    "sign in to confirm your age",
    "content warning",
]


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


def is_permanent_error(error_msg):
    """Check if an error is permanent (no point retrying)."""
    lower = error_msg.lower()
    return any(reason in lower for reason in PERMANENT_ERRORS)


class YtDlpGui:
    def __init__(self, root):
        self.root = root
        self.root.title("yt-dlp GUI")
        self.root.minsize(600, 520)
        self.root.resizable(True, True)

        self.config = load_config()
        self.downloading = False
        self.process = None
        self.output_queue = queue.Queue()
        self.errors_and_warnings = []
        self.detail_log_visible = False

        # Failure tracking
        self.current_video_url = None
        self.current_video_id = None
        self.failed_videos = []  # list of {"url": ..., "id": ..., "error": ..., "permanent": bool}

        self._build_ui()
        self._check_ytdlp()

    def _build_ui(self):
        padding = {"padx": 10, "pady": 5}
        self.root.columnconfigure(0, weight=1)

        style = ttk.Style()
        style.configure("TButton", font=("Segoe UI", 11))

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

        # --- Progress Section ---
        progress_frame = ttk.LabelFrame(self.root, text="Progress", padding=10)
        progress_frame.grid(row=4, column=0, sticky="ew", **padding)
        progress_frame.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="Idle")
        status_label = ttk.Label(progress_frame, textvariable=self.status_var, font=("Segoe UI", 10, "bold"))
        status_label.grid(row=0, column=0, sticky="w")

        self.item_var = tk.StringVar(value="")
        item_label = ttk.Label(progress_frame, textvariable=self.item_var, font=("Segoe UI", 9))
        item_label.grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100, mode="determinate")
        self.progress_bar.grid(row=2, column=0, sticky="ew", pady=(5, 0))

        self.detail_var = tk.StringVar(value="")
        detail_label = ttk.Label(progress_frame, textvariable=self.detail_var, font=("Segoe UI", 8))
        detail_label.grid(row=3, column=0, sticky="w", pady=(2, 0))

        # --- Summary Section (hidden until needed) ---
        self.summary_frame = ttk.LabelFrame(self.root, text="Failed Videos", padding=10)
        self.summary_frame.columnconfigure(0, weight=1)
        self.summary_frame.rowconfigure(0, weight=1)

        self.summary_text = tk.Text(self.summary_frame, height=6, wrap="word", state="disabled", font=("Consolas", 9))
        self.summary_text.grid(row=0, column=0, sticky="nsew")

        summary_scroll = ttk.Scrollbar(self.summary_frame, orient="vertical", command=self.summary_text.yview)
        summary_scroll.grid(row=0, column=1, sticky="ns")
        self.summary_text.configure(yscrollcommand=summary_scroll.set)

        copy_summary_btn = ttk.Button(self.summary_frame, text="Copy Summary", command=self._copy_summary)
        copy_summary_btn.grid(row=1, column=0, sticky="w", pady=(5, 0))

        # --- Detailed Log Section (collapsible) ---
        log_toggle_frame = ttk.Frame(self.root)
        log_toggle_frame.grid(row=6, column=0, sticky="ew", padx=10, pady=(5, 0))
        log_toggle_frame.columnconfigure(1, weight=1)

        self.toggle_btn = ttk.Button(log_toggle_frame, text="Show Detailed Log", width=20, command=self._toggle_log)
        self.toggle_btn.grid(row=0, column=0)

        self.copy_errors_btn = ttk.Button(log_toggle_frame, text="Copy Errors & Warnings", width=22, command=self._copy_errors)
        self.copy_errors_btn.grid(row=0, column=2)

        self.log_frame = ttk.Frame(self.root)
        # log_frame is NOT gridded by default (collapsed)
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(self.log_frame, height=12, wrap="word", state="disabled", font=("Consolas", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _toggle_log(self):
        if self.detail_log_visible:
            self.log_frame.grid_forget()
            self.root.rowconfigure(7, weight=0)
            self.toggle_btn.configure(text="Show Detailed Log")
            self.detail_log_visible = False
        else:
            self.log_frame.grid(row=7, column=0, sticky="nsew", padx=10, pady=(0, 10))
            self.root.rowconfigure(7, weight=1)
            self.toggle_btn.configure(text="Hide Detailed Log")
            self.detail_log_visible = True

    def _show_summary(self):
        """Show the failed videos summary panel."""
        if not self.failed_videos:
            self.summary_frame.grid_forget()
            return

        self.summary_frame.grid(row=5, column=0, sticky="nsew", padx=10, pady=5)

        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", tk.END)

        for entry in self.failed_videos:
            video_id = entry["id"] or "unknown"
            error = entry["error"]
            permanent = entry["permanent"]
            tag = " [will not retry — permanent]" if permanent else " [retry failed]"

            url = entry["url"] or f"https://www.youtube.com/watch?v={video_id}"
            self.summary_text.insert(tk.END, f"{video_id}: {error}{tag}\n  {url}\n\n")

        self.summary_text.configure(state="disabled")

    def _hide_summary(self):
        self.summary_frame.grid_forget()

    def _copy_summary(self):
        if not self.failed_videos:
            return
        lines = []
        for entry in self.failed_videos:
            video_id = entry["id"] or "unknown"
            error = entry["error"]
            permanent = entry["permanent"]
            tag = " [permanent]" if permanent else " [retry failed]"
            url = entry["url"] or f"https://www.youtube.com/watch?v={video_id}"
            lines.append(f"{video_id}: {error}{tag}\n  {url}")

        self.root.clipboard_clear()
        self.root.clipboard_append("\n\n".join(lines))
        self._flash_button(
            self.summary_frame.winfo_children()[-1],  # copy button
            f"Copied {len(self.failed_videos)} items!",
        )

    def _copy_errors(self):
        if not self.errors_and_warnings:
            self.root.clipboard_clear()
            self.root.clipboard_append("No errors or warnings.")
            self._flash_button(self.copy_errors_btn, "Nothing to copy")
            return

        text = "\n".join(self.errors_and_warnings)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._flash_button(self.copy_errors_btn, f"Copied {len(self.errors_and_warnings)} items!")

    def _flash_button(self, button, message):
        original = button.cget("text")
        button.configure(text=message)
        self.root.after(2000, lambda: button.configure(text=original))

    def _check_ytdlp(self):
        if not shutil.which("yt-dlp"):
            self.status_var.set("Warning: yt-dlp not found in PATH")
            self._log_detail("yt-dlp is not installed or not in your system PATH.\n")
            self._log_detail("Install it with: pip install yt-dlp\n")
            self._log_detail("Or download from: https://github.com/yt-dlp/yt-dlp#installation\n")

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

    def _log_detail(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _clear_all(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")
        self.errors_and_warnings.clear()
        self.failed_videos.clear()
        self.current_video_url = None
        self.current_video_id = None
        self.progress_var.set(0)
        self.item_var.set("")
        self.detail_var.set("")
        self._hide_summary()

    def _parse_line(self, line):
        """Parse a yt-dlp output line and update the user-friendly progress."""
        stripped = line.strip()

        # Track the current video URL being extracted
        m = RE_EXTRACTING_URL.match(stripped)
        if m:
            self.current_video_url = m.group(1).strip()
            return

        # Track errors and warnings
        m = RE_ERROR.search(stripped)
        if m:
            error_msg = m.group(1)
            self.errors_and_warnings.append(stripped)

            # Extract video ID from error like "ERROR: [youtube] ABC123: ..."
            error_id_match = re.match(r"\[youtube\]\s+(\S+?):", error_msg)
            video_id = error_id_match.group(1) if error_id_match else self.current_video_id

            self.failed_videos.append({
                "url": self.current_video_url,
                "id": video_id,
                "error": error_msg,
                "permanent": is_permanent_error(error_msg),
            })

            self.status_var.set("Error")
            self.item_var.set(error_msg[:80])
            return

        m = RE_WARNING.search(stripped)
        if m:
            self.errors_and_warnings.append(stripped)
            return

        # Playlist item progress
        m = RE_DOWNLOAD_ITEM.match(stripped)
        if m:
            current, total = m.group(1), m.group(2)
            self.item_var.set(f"Item {current} of {total}")
            self.progress_var.set(0)
            self.detail_var.set("")
            self.current_video_url = None
            self.current_video_id = None
            return

        # Extracting video info
        m = RE_EXTRACTING.match(stripped)
        if m:
            self.current_video_id = m.group(1)
            self.detail_var.set(f"Extracting: {m.group(1)}")
            return

        # Download destination (shows filename)
        m = RE_DOWNLOAD_DEST.match(stripped)
        if m:
            filename = os.path.basename(m.group(1))
            self.item_var.set(filename[:80])
            return

        # Download progress percentage
        m = RE_DOWNLOAD_PROGRESS.search(stripped)
        if m:
            pct = float(m.group(1))
            size = m.group(2)
            speed = m.group(3)
            eta = m.group(4)
            self.progress_var.set(pct)
            self.detail_var.set(f"{pct:.1f}% of {size}  |  {speed}  |  ETA {eta}")
            return

        # Download complete for a file
        m = RE_DOWNLOAD_COMPLETE.search(stripped)
        if m:
            self.progress_var.set(100)
            self.detail_var.set("Download complete, processing...")
            return

        # Already downloaded
        m = RE_ALREADY_DOWNLOADED.match(stripped)
        if m:
            filename = os.path.basename(m.group(1))
            self.item_var.set(f"Already downloaded: {filename[:60]}")
            self.progress_var.set(100)
            return

        # Merging
        m = RE_MERGING.match(stripped)
        if m:
            self.detail_var.set("Merging video and audio...")
            return

    def _build_cmd(self, url):
        """Build the yt-dlp command for a given URL."""
        download_dir = self.dir_var.get()
        cmd = ["yt-dlp", "--newline", "-o", os.path.join(download_dir, "%(title)s.%(ext)s")]
        quality = self.quality_var.get()
        cmd.extend(QUALITY_OPTIONS.get(quality, []))
        cmd.append(url)
        return cmd

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

        self._clear_all()
        self.downloading = True
        self.download_btn.configure(state="disabled")
        self.status_var.set("Downloading...")

        cmd = self._build_cmd(url)

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

    def _run_retry(self, retryable):
        """Retry each failed video URL individually."""
        for i, entry in enumerate(retryable, 1):
            url = entry["url"] or f"https://www.youtube.com/watch?v={entry['id']}"
            self.output_queue.put(("__RETRY_STATUS__", i, len(retryable), entry["id"] or url))

            try:
                cmd = self._build_cmd(url)
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

                if self.process.returncode == 0:
                    self.output_queue.put(("__RETRY_OK__", entry["id"]))
            except Exception as e:
                self.output_queue.put(f"Retry error: {e}\n")

        self.output_queue.put(("__RETRY_DONE__",))

    def _poll_output(self):
        while True:
            try:
                item = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if isinstance(item, tuple):
                tag = item[0]

                if tag == "__DONE__":
                    return_code = item[1]
                    self.process = None

                    # Check if we have retryable failures
                    retryable = [v for v in self.failed_videos if not v["permanent"]]
                    if retryable:
                        # Start auto-retry in background
                        permanent_count = len(self.failed_videos) - len(retryable)
                        self.status_var.set("Retrying failed videos...")
                        self.item_var.set(
                            f"{len(retryable)} to retry, {permanent_count} permanently failed"
                        )
                        self.progress_var.set(0)
                        self.detail_var.set("")

                        # Clear retryable failures — they'll be re-added if retry fails
                        self.failed_videos = [v for v in self.failed_videos if v["permanent"]]

                        self._log_detail("\n--- Auto-retrying failed videos ---\n\n")
                        thread = threading.Thread(target=self._run_retry, args=(retryable,), daemon=True)
                        thread.start()
                    else:
                        self._finish_download(return_code)
                        return

                elif tag == "__RETRY_STATUS__":
                    _, current, total, video_id = item
                    self.item_var.set(f"Retry {current} of {total}: {video_id}")
                    self.progress_var.set(0)
                    self.detail_var.set("")

                elif tag == "__RETRY_OK__":
                    video_id = item[1]
                    self._log_detail(f"Retry succeeded for {video_id}\n")

                elif tag == "__RETRY_DONE__":
                    self.process = None
                    self._finish_download(0 if not self.failed_videos else 1)
                    return
            else:
                self._log_detail(item)
                self._parse_line(item)

        if self.downloading:
            self.root.after(100, self._poll_output)

    def _finish_download(self, return_code):
        """Finalize the download process and show summary."""
        self.downloading = False
        self.download_btn.configure(state="normal")

        if not self.failed_videos:
            self.status_var.set("Complete")
            self.progress_var.set(100)
            self.detail_var.set("All downloads finished successfully.")
        else:
            permanent = [v for v in self.failed_videos if v["permanent"]]
            other = [v for v in self.failed_videos if not v["permanent"]]

            parts = []
            if permanent:
                parts.append(f"{len(permanent)} permanently unavailable")
            if other:
                parts.append(f"{len(other)} failed after retry")

            self.status_var.set("Complete with errors")
            self.item_var.set(f"{len(self.failed_videos)} video(s) could not be downloaded: {', '.join(parts)}")
            self.detail_var.set("")
            self._show_summary()

        if self.errors_and_warnings and not self.failed_videos:
            self.item_var.set(
                f"Finished with {len(self.errors_and_warnings)} warning(s) — use 'Copy Errors & Warnings' to share"
            )


def main():
    root = tk.Tk()
    YtDlpGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
