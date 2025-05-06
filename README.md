# Building the Edge TTS Converter Application

This guide explains how to build the Edge TTS Converter application from the provided source files on macOS and Windows.

## Prerequisites

Before you begin, ensure you have the following installed on your system:

* **Python**: Version 3.8 or newer is recommended.
    * You can download Python from [python.org](https://www.python.org/).
    * During installation on Windows, make sure to check the box that says "Add Python to PATH".
* **pip**: Python's package installer. It usually comes with Python.
* **PyInstaller**: The tool used to bundle the application.
* **(Optional but Recommended) A Virtual Environment Tool**: Like `venv` (built-in) or `conda` if you prefer. While not strictly required by these instructions for a one-off build, it's good practice for managing Python projects and their dependencies.

## Setup Instructions (Common for macOS and Windows)

1.  **Download and Unzip:**
    * Download the provided `.zip` file (e.g., `FastestTTS_App.zip`).
    * Extract/unzip its contents to a folder on your computer. This folder will be referred to as your "project folder" (e.g., `FastestTTS_App`).

2.  **Open Terminal / Command Prompt:**
    * **macOS:** Open Terminal (you can find it in Applications > Utilities).
    * **Windows:** Open Command Prompt or PowerShell (search for them in the Start Menu).

3.  **Navigate to Project Folder:**
    * In your Terminal or Command Prompt, use the `cd` (change directory) command to go into the project folder you just unzipped.
        * Example: `cd path/to/your/FastestTTS_App`
        * (You can often drag the folder icon from your file explorer into the terminal window after typing `cd ` to get the correct path).

## Installing PyInstaller (If not already installed)

If you don't have PyInstaller installed in the Python environment you intend to use, install it from your terminal (while inside the project folder, or globally if you prefer, though project-specific is better):

* **For most systems (using pip with your default Python):**
    ```bash
    python -m pip install pyinstaller
    ```
* **On macOS, if `python` defaults to an older Python 2, you might need `python3`:**
    ```bash
    python3 -m pip install pyinstaller
    ```
* **If using a Conda environment, and it's active:**
    ```bash
    conda install pyinstaller
    ```
    or
    ```bash
    python -m pip install pyinstaller
    ```

## Building the Application

The process is similar for both macOS and Windows once the prerequisites are met and you are in the project folder in your terminal.

**Crucial First Step: Install `edge_tts`**

Before running PyInstaller, it's vital to ensure the `edge_tts` library and its dependencies are installed in the Python environment that PyInstaller will use.

1.  **Ensure you are in the project folder in your Terminal/Command Prompt.**
2.  Install `edge_tts`:
    * **For most systems:**
        ```bash
        python -m pip install edge_tts
        ```
    * **On macOS (if `python` is Python 2, or to be specific):**
        ```bash
        python3 -m pip install edge_tts
        ```
    This command installs `edge_tts` into the Python environment that your `python` (or `python3`) command points to.

**Now, run the PyInstaller build command:**

* **For most systems (including Anaconda environments where `python` points to the environment's Python):**
    ```bash
    python -m PyInstaller EdgeTTSConverter.spec
    ```
* **On macOS, if you specifically need to use `python3`:**
    ```bash
    python3 -m PyInstaller EdgeTTSConverter.spec
    ```

This command tells PyInstaller to use the `EdgeTTSConverter.spec` file (which is included in the zip) to build the application. PyInstaller will create two new folders: `build` and `dist`.

## Locating and Running the Application

* **On macOS:**
    1.  After the build completes, navigate to the `dist` folder inside your project folder.
    2.  Inside `dist`, you will find a folder named `EdgeTTSConverter`.
    3.  Inside *that* folder, you'll find **`EdgeTTSConverter.app`**. This is your application. Double-click it to run.

* **On Windows:**
    1.  After the build completes, navigate to the `dist` folder inside your project folder.
    2.  Inside `dist`, you will find a folder named `EdgeTTSConverter`.
    3.  Inside *that* folder, you'll find **`EdgeTTSConverter.exe`**. This is your application. Double-click it to run.
    4.  **Important:** All the other files and folders within `dist/EdgeTTSConverter/` are necessary for the `.exe` to work. Keep them together.

## Troubleshooting

### ModuleNotFoundError: No module named 'edge_tts' (or similar)

This is the most common issue and usually means PyInstaller couldn't find the `edge_tts` library when the bundled application starts, even if it was installed on your system.

**Solution Steps:**

1.  **Close the application** if it's (partially) running or showing the error.
2.  **Open your Terminal or Command Prompt** and use `cd` to navigate into your project folder (e.g., `FastestTTS_App`).
3.  **Uninstall `edge_tts` (to ensure a clean state for the correct environment):**
    * Run: `python -m pip uninstall edge_tts` (or `python3 -m pip uninstall edge_tts` on Mac if needed). Confirm with 'y' if prompted.
4.  **Reinstall `edge_tts` DIRECTLY in the context of your project folder's Python environment:**
    * **Crucially, ensure you are still in your project folder in the terminal.**
    * Run: `python -m pip install edge_tts` (or `python3 -m pip install edge_tts` on Mac if needed).
    * This step is vital to ensure `edge_tts` is installed in the Python environment that PyInstaller will use for the build.
5.  **Clean previous build attempts:**
    * In your project folder, **delete the `build` folder and the `dist` folder** entirely. This prevents old files from interfering.
6.  **Re-run the PyInstaller build command:**
    * `python -m PyInstaller EdgeTTSConverter.spec` (or `python3 -m PyInstaller EdgeTTSConverter.spec` on Mac).
7.  **Test the application again** from the newly created `dist` folder.

**Other Troubleshooting Tips:**

* **Python Environment Consistency:** If you have multiple Python installations (e.g., system Python, Homebrew Python, Anaconda), ensure that the `python` command in your terminal (the one you use for `pip install` and `PyInstaller`) is the *same* Python environment where `edge_tts` and `PyInstaller` are installed and where your script runs correctly during development.
    * You can check your Python version and path with `python --version` and `python -c "import sys; print(sys.executable)"`.
* **Check PyInstaller Output:** When PyInstaller runs, it prints a lot of information. Look for any "WARNING" messages in the output, as they might give clues about missing modules or other issues.
* **Antivirus Software (Windows):** Sometimes, antivirus software can interfere with PyInstaller or falsely flag the created `.exe`. Try temporarily disabling your antivirus if you suspect this (do so at your own risk and only if you trust the source code).

---

Good luck with building and running the application!

