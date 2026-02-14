# yt-dlp GUI

A simple, user-friendly graphical interface for [yt-dlp](https://github.com/yt-dlp/yt-dlp), making video downloads accessible without the command line.

## Features

- **Easy URL Input**: Paste YouTube video or playlist links
- **Download Directory Selection**: Choose where your videos are saved
- **Quality Options**: Select video quality or download audio-only
- **Progress Tracking**: See download status in real-time
- **Clean Interface**: Simple, straightforward design focused on usability

## Prerequisites

- **Python 3.8+**
- **yt-dlp**: Must be installed and accessible from command line
  - Install via pip: `pip install yt-dlp`
  - Or download from: https://github.com/yt-dlp/yt-dlp#installation
- **Deno** (required by yt-dlp for YouTube downloads):
  - Windows: `winget install --id=DenoLand.Deno`
  - macOS: `brew install deno`
  - Linux: `curl -fsSL https://deno.land/install.sh | sh`
  - See the [yt-dlp EJS wiki](https://github.com/yt-dlp/yt-dlp/wiki/EJS) for details

No additional Python packages required — uses only standard library (tkinter).

## Installation

Clone the repository:
```bash
git clone <repository-url>
cd yt-dlp-gui
```

## Usage

Run the application:
```bash
python main.py
```

1. Paste a YouTube video or playlist URL (or use the Paste button)
2. Select your download directory via Browse
3. Choose quality (Best, 1080p, 720p, 480p, or Audio Only)
4. Click Download
5. Watch progress in the log area

Settings (download directory, quality) are saved automatically between sessions.

## Roadmap

- [x] Product Requirements Document
- [x] Basic GUI implementation
- [x] Download functionality
- [x] Settings persistence
- [ ] Packaging for distribution

## Contributing

This is a personal project, but suggestions and bug reports are welcome via issues.

## License

*License to be determined*

## Acknowledgments

- Built on top of [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- Inspired by the need for simple, accessible video download tools
