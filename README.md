
# Parametric Fingerboard

A user-friendly, standalone application for climbers to design and interact with parametric fingerboards, including generating 3D-printable models. No programming knowledge required—just download and run!


## Features
- Intuitive GUI for parametric fingerboard design
- Generates 3D models suitable for 3D printing
- No installation or setup required for end-users (standalone executable)
- Built with Python for cross-platform compatibility


## Quick Start (for End-Users)

You do not need to download or install the entire project. Simply download the precompiled standalone executable for your operating system (Windows, Linux, or macOS) from the `dist/` folder or the project’s release page. Double-click the file to launch the app—no Python or additional software required.

**Note:** If you do not see an executable for your operating system, it may not have been published yet. Please check back later or contact the author.

---

## For Developers: Setup & Building the Executable

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/parametric_fingerboard.git
cd parametric_fingerboard
```

### 2. Install Dependencies
It is recommended to use a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
If `requirements.txt` does not exist, install dependencies manually:
```bash
pip install pyinstaller
# Add any other dependencies your project needs
```

### 3. Generate the Standalone Executable with PyInstaller
Run the following command from the project root:
```bash
pyinstaller --onefile --windowed src/parametric_fingerboard/app.py
```
- `--onefile`: Bundle everything into a single executable
- `--windowed`: Prevents a terminal window from opening (for GUI apps)

The resulting executable will be located in the `dist/` directory.

#### Example (Linux):
```bash
./dist/app
```
#### Example (Windows):
Double-click `dist/app.exe`

### 4. Distribute
Share the file in `dist/` with your users. They do not need to install Python or any dependencies.

---

## Notes
- Build the executable on the same OS you intend to distribute for (Windows for Windows, Linux for Linux, etc.).
- Test the executable on a clean machine to ensure it works as expected.
- For advanced options (icons, splash screens, etc.), see the [PyInstaller documentation](https://pyinstaller.org/).

---



## Disclaimer

This software generates 3D models intended for 3D printing. Improper use, design, or manufacturing of these models may result in injury, equipment damage, or other harm. The author is not responsible for any injury, damage, or loss resulting from the use, misuse, or manufacturing of models created with this software. Use at your own risk. No permission is granted to use, copy, modify, or distribute this software without explicit written consent from the author.

---

## Contact
For questions, suggestions, or contributions, please open an issue or pull request on GitHub.
