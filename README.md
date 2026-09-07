# VST Helper
 An easy way to run Windows VST, CLAP, and LV2 audio plugins on Linux.

 This repo is currently just a writeup for something I plan to develop in the future.  If this sounds interesting, feel free to give it a star, or an issue report if something architecturally seems useful, or a pull request if you want to do it yourself!

# Goals
This project is built on the back of yabridge, which is a great wrapper that allows Windows VSTs to run on Linux, however its interface is CLI only, and while other GUIs exist for it, this project aims to automate installation as well, since yabridge requires Wine to work, and itself needs to be installed which is non-trivial for a non-technical user.  This project bridges that gap.

To use it
1 - Run the installer.
2 - The installer makes sure you have everything you need to get started.
3 - Get a Windows plugin .exe or raw .vst3 plugin, run it in the app.
4 - VST Helper will do everything needed to integrate that plugin so it can be run in your VST hosts like REAPER.
5 - Maybe install a Windows DAW like FL Studio or Ableton while you're at it...

# Technical Details

 - Python and PyQt6 based
 - Install shell script that installs Wine, as well as yabridge, then creates .desktop integrations for the application.
 - Also prompts the user for audio optimizations, like installing a realtime kernel, adding the user to realtime group, etc.
 - Application itself allows you to specify where you want your Windows VSTs stored (Linux versions will always go to ~/.vst3, ~/.vst, ~/.clap, or ~/.lv2 respectively, with an option to change these locations) and create a Wine prefix in that location
 - This will also automatically refresh yabridge when installing a new plugin, with a manual refresh in settings
 - A wine runner can also be specified per plugin, as well as specific wine tweaks so that each can be fiddled with to run perfectly.
 - Can also set a WINELOADER environment variable at the DAW level so that said Wine runner will be more likely to be respected instead of falling back to system wine, which is often newer and will not work as well with yabridge.
 - Apply custom known fixes, such as:
    - installing dxvk for plugin UI updating
    - Importing FL Studio key into the registry for manual activation
 
# Caveats
Wine is great, and most plugins for Windows will work on Linux, however some just will not, especially those with aggressive license checks, such as iZotope plugins.  It is also difficult to test across distros, most of my testing is done on CachyOS so Arch based distros will have the best results.

# Testing
Clone repo, and from project directory:

python -m venv .venv
.venv/bin/python -m pip install -e .[dev]
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install pytest
source .venv/bin/activate.fish # (for fish Terminals)
source .venv/bin/activate 
python -m pytest -v
