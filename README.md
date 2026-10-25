# LT200B-gui
A web-based label maker for the Dymo LetraTag LT200B, built with Flask.
The Dymo LetraTag 200B is a Bluetooth label printer that comes with an iOS and Android app. The app only allows you to print text using a couple of installed fonts.
This Python app provides a relatively user friendly experience on the Desktop to compose and print text and image labels from your computer, using a local web UI.

## Features
- Print labels on a Dymo LT200B printer from your desktop browser (mostly tested on Linux)
- Stepped label builder: starts with one text field, add any number of text and image assets in any order; images are placed inline between text
- Live preview that renders the exact 1-bit bitmap sent to the printer, shown at full 12 mm tape height
- Per-text-asset height setting in mm; text is scaled so the actual glyph ink matches the chosen height, and always fits the printable area of the tape
- Invert option per image asset (e.g. for white-on-dark printing)
- ~2 mm of blank tape is fed before and after each label
- Scan for nearby printers and pick yours from a list; the last used printer is remembered
- Special characters (å, ä, ö, é, ü, ...) are supported via a bundled font (Liberation Sans)
- Serves on http://127.0.0.1:8000 only - it accepts local connections, nothing is exposed to the network

## Requirements
- A Bluetooth adapter (BLE). On Linux, BlueZ must be available.
- A desktop browser.

## Usage
### From the source
This project uses [uv](https://docs.astral.sh/uv/) for dependency management. Install uv first:

`curl -LsSf https://astral.sh/uv/install.sh | sh`

Then install the dependencies (creates a virtual environment in `.venv`):

`uv sync`

Run the app (starts the server and opens the UI in your browser):

`uv run lt200b`

### Project layout

```
src/lt200b/
  app.py        Flask app, API endpoints, entry point (uv run lt200b)
  config.py     ConfigStore: persisted settings (last printer)
  geometry.py   PrintGeometry: calibrated mm/dot conversion factors
  job.py        JobEncoder: label image -> chunked print job
  printer.py    PrinterClient: BLE scan and print transport
  render.py     LabelRenderer: text/emoji/image assets -> label image
  fonts/        Bundled Liberation Sans and Noto Emoji (with licenses)
  templates/    Web UI
tests/          pytest suite (rendering, job encoding, API, config)
```

### Development

Type checking and tests:

```
uv run mypy src tests
uv run pytest
```

### Building a label
1. Enter your printer's MAC address or use **Scan for Printer** and pick it from the list.
2. Type the label text. Use **+ Text** / **+ Image** to add more assets; each asset can be removed with ✕.
3. Optionally set the text height per text field (2-5 mm; the printer can only print the middle ~5.2 mm of a 12 mm tape) and invert images.
4. Check the preview, then hit **Print Label**.

### Release version
Automated builds are produced by the GitHub Actions workflow on every push to main. Currently available for Linux and Windows.

#### Linux
Unzip the file.

`chmod +x LT200B`

Run the executable.

#### Windows
Unzip the file.
Run the executable.

### Building the executables yourself
PyInstaller is included as a dev dependency:

```
uv sync
uv run pyinstaller src/lt200b/__main__.py --name LT200B --onefile --paths src \
  --add-data "src/lt200b/fonts:lt200b/fonts" \
  --add-data "src/lt200b/templates:lt200b/templates" \
  --icon=icon.png
```

(On Windows, use `;` instead of `:` in the `--add-data` arguments.)

## Configuration
The last used printer MAC address is stored in a config file located with `platformdirs.user_config_dir` (e.g. `~/.config/LT200B-GUI` on Linux).

## Screenshots
Screenshots of the previous tkinter version (the web UI has a similar layout):

![Main window](https://github.com/sgilissen/LT200B-gui/blob/main/screenshots/main.png?raw=true)
![Scanning for devices](https://github.com/sgilissen/LT200B-gui/blob/main/screenshots/scan.png?raw=true)

## Acknowledgements
[Alexander Horn](https://github.com/alexhorn) for his [LT200B Python repository](https://github.com/alexhorn/lt200b). His code has been used as a base here, wrapped in a web UI with scanning, a label builder and a live preview.
