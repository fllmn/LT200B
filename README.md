# LT200B-gui
Python-based (Flask) web UI to print labels on the Dymo LetraTag LT200B.
The Dymo LetraTag 200B is a Bluetooth label printer that comes with an iOS and Android app. The app only allows you to print text using a couple of installed fonts. 
This Python app aims to provide a relatively user friendly experience on the Desktop to print text and image labels from your computer.

## Features
- Allows printing labels on a Dymo LT200B printer from desktops (mostly tested in Linux)
- Scanning functionality to scan for your printer
- Stepped label builder: start with a text field, add multiple text and image assets in any order
- Live preview of the printed tag at full 12 mm tape height
- Text height selectable in mm, tags always fit the printable area of the tape
- Special characters (å, ä, ö, é, ü, ...) are supported via a bundled font
- Web UI served on http://127.0.0.1:8000, local connections only

## Usage
### From the source
This project uses [uv](https://docs.astral.sh/uv/) for dependency management. Install uv first:

`curl -LsSf https://astral.sh/uv/install.sh | sh`

Then install the dependencies (creates a virtual environment in `.venv`):

`uv sync`

Run the app (opens the UI in your browser):

`uv run main.py`

### Release version
Currently available for Linux and Windows. 
#### Linux
Unzip the file. 

`chmod +x LT200B`

Run the executable

#### Windows
Unzip the file. 
Run the executable.

## Screenshots

![Main window](https://github.com/sgilissen/LT200B-gui/blob/main/screenshots/main.png?raw=true)
![Scanning for devices](https://github.com/sgilissen/LT200B-gui/blob/main/screenshots/scan.png?raw=true)

## Acknowledgements
[Alexander Horn](https://github.com/alexhorn) for his [LT200B Python repository](https://github.com/alexhorn/lt200b). His code has been used as a base here, I've just wrapped it in a GUI and added the scanning functionality.

