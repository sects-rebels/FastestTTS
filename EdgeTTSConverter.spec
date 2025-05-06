# -*- mode: python ; coding: utf-8 -*-

import sys
import os

block_cipher = None

# --- Configuration for FFmpeg and Icons ---
# This section helps PyInstaller find your FFmpeg binaries and optional icons.

# Base directory of your project (where this spec file is located)
# MODIFIED: Use os.getcwd() as PyInstaller is run from this directory.
BASE_DIR = os.getcwd() # <<< THIS LINE IS MODIFIED

ffmpeg_src_path = None
# The destination subfolder within the bundled app where ffmpeg will be placed.
# Your Python script's get_ffmpeg_path() function is designed to look here.
ffmpeg_dest_subfolder_in_bundle = 'ffmpeg'

if sys.platform == "win32":
    ffmpeg_src_path = os.path.join(BASE_DIR, 'ffmpeg_binaries', 'win', 'ffmpeg.exe')
elif sys.platform == "darwin":  # macOS
    ffmpeg_src_path = os.path.join(BASE_DIR, 'ffmpeg_binaries', 'mac', 'ffmpeg')
# Add elif for linux if you plan to build on Linux:
# elif sys.platform.startswith("linux"):
#     ffmpeg_src_path = os.path.join(BASE_DIR, 'ffmpeg_binaries', 'linux', 'ffmpeg')
else:
    print(f"WARNING: Unsupported platform {sys.platform} for FFmpeg bundling. FFmpeg will not be included automatically by this spec logic.")

datas_list = []
if ffmpeg_src_path and os.path.exists(ffmpeg_src_path):
    # (source_path_on_disk, destination_path_in_bundle)
    datas_list.append((ffmpeg_src_path, ffmpeg_dest_subfolder_in_bundle))
    print(f"INFO: Scheduled bundling of FFmpeg from: {ffmpeg_src_path} to '{ffmpeg_dest_subfolder_in_bundle}' in bundle.")
else:
    if ffmpeg_src_path: # Only print error if we expected to find it for the current build OS
         print(f"ERROR: FFmpeg executable not found at expected path: {ffmpeg_src_path}. It will NOT be bundled.")
    else:
        print(f"INFO: No specific FFmpeg path configured for this platform ({sys.platform}) in the spec file. App will rely on system PATH if FFmpeg not found by script's other checks.")


# --- Icon configuration ---
icon_path = None
if sys.platform == "win32":
    icon_path_candidate = os.path.join(BASE_DIR, 'icons', 'app_icon.ico')
    if os.path.exists(icon_path_candidate):
        icon_path = icon_path_candidate
    else:
        print(f"INFO: Windows icon app_icon.ico not found in 'icons' folder. Using default icon.")
elif sys.platform == "darwin":  # macOS
    icon_path_candidate = os.path.join(BASE_DIR, 'icons', 'app_icon.icns')
    if os.path.exists(icon_path_candidate):
        icon_path = icon_path_candidate
    else:
        print(f"INFO: macOS icon app_icon.icns not found in 'icons' folder. Using default icon.")
# For Linux, icons are usually handled by .desktop files, not directly in the binary in the same way.

if icon_path:
    print(f"INFO: Using icon: {icon_path}")


a = Analysis(
    ['TTSApp.py'], # Your script name
    pathex=[BASE_DIR], # Tells PyInstaller to look for imports in your project directory
    binaries=[],
    datas=datas_list,  # This includes FFmpeg
    hiddenimports=[
        'edge_tts',
        'edge_tts.constants',
        'edge_tts.submaker',
        'edge_tts.tts',
        'edge_tts.util',
        'edge_tts.voice',
        'aiohttp',
        'async_timeout',
        'multidict',
        'yarl',
        'certifi',
        'charset_normalizer', # Often a dependency of requests/aiohttp
        'idna',             # Often a dependency of requests/aiohttp
        'tkinter',          # Explicitly include tkinter just in case
        'asyncio',          # Explicitly include asyncio
        # Add other submodules or dependencies if PyInstaller misses them during testing
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_options = {
    'name': 'EdgeTTSConverter', # The name of your executable
    'debug': False,
    'bootloader_ignore_signals': False,
    'strip': False,
    'upx': True,  # Compresses the executable; can sometimes cause issues or AV flags. Set to False if problems.
    'upx_exclude': [],
    'runtime_tmpdir': None, # Uses default temp location
    'console': False,      # Crucial: False for GUI applications (no background console window)
                           # True for command-line applications
}
if icon_path:
    exe_options['icon'] = icon_path

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    **exe_options
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas, # This ensures FFmpeg (from datas_list) is collected into the final app
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EdgeTTSConverter', # The name of the output folder in 'dist'
)

# --- macOS Specific .app Bundle Configuration ---
if sys.platform == "darwin": # Only attempt to create .app bundle on macOS
    app = BUNDLE(
        coll,
        name='EdgeTTSConverter.app', # Name of the .app bundle
        icon=icon_path, # Must be a .icns file for macOS .app bundles
        bundle_identifier='com.aidenhall.edgettsconverter', # Optional: Replace with your own unique identifier (e.g. com.yourname.appname)
        # You can add more Info.plist settings here if needed, for example:
        # info_plist={
        #    'NSPrincipalClass': 'NSApplication',
        #    'NSHighResolutionCapable': 'True',
        #    'CFBundleShortVersionString': '1.0.0', # Your app version
        #    'CFBundleDisplayName': 'Edge TTS Converter', # Name shown in Finder
        # }
    )
