#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Apr 29 13:35:39 2025
Modified on Wed Apr 30 15:30:00 2025
Further modified for PyInstaller bundling with FFmpeg

@author: aidenhall

Requires:
- edge-tts: pip install edge-tts
- ffmpeg: Will attempt to use bundled ffmpeg or ffmpeg in system PATH.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import edge_tts
import asyncio
import threading
import os
import time
import math
import tempfile
import queue # Import the queue module
import subprocess # For running ffmpeg
import sys # For checking platform
import shutil # For checking ffmpeg path
import statistics # For mean and stdev

# --- Configuration ---
TEXT_CHUNK_SIZE = 2500 # Characters
QUEUE_CHECK_INTERVAL_MS = 100 # How often to check the queue for updates (milliseconds)
MAX_CONCURRENT_TASKS = 10 # Max number of TTS requests to run in parallel
CI_Z_SCORE = 1.96 # Z-score for 95% confidence interval

# <<< MODIFIED/ADDED START >>>
# --- FFmpeg Path Detection ---
def get_ffmpeg_path():
    """
    Determines the path to ffmpeg.
    1. Checks if ffmpeg is bundled with the application (common for PyInstaller).
       - Looks in a 'ffmpeg' subdirectory of the bundle.
       - Looks in the main directory of the bundle.
    2. Checks if ffmpeg is in the system's PATH.
    Returns the absolute path to ffmpeg if found, otherwise None.
    """
    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    bundle_dir = None

    # Check if running in a bundled app (PyInstaller)
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller one-file bundle, files are in a temporary _MEIPASS folder
            bundle_dir = sys._MEIPASS
            print(f"Running in one-file bundle, MEIPASS: {bundle_dir}")
        else:
            # PyInstaller one-folder bundle or other bundlers
            bundle_dir = os.path.abspath(os.path.dirname(sys.executable))
            print(f"Running in one-folder bundle, executable dir: {bundle_dir}")
    # For development (not frozen), you might want to check relative to script for testing
    # else:
    #    bundle_dir = os.path.abspath(os.path.dirname(__file__))
    #    print(f"Running in development, script dir: {bundle_dir}")


    if bundle_dir:
        # Check in 'ffmpeg' subdirectory of the bundle
        # This is the preferred location for bundled ffmpeg
        bundled_ffmpeg_path_subdir = os.path.join(bundle_dir, "ffmpeg", ffmpeg_name)
        print(f"Checking for bundled ffmpeg at: {bundled_ffmpeg_path_subdir}")
        if os.path.exists(bundled_ffmpeg_path_subdir) and os.access(bundled_ffmpeg_path_subdir, os.X_OK):
            print(f"Found bundled ffmpeg at: {bundled_ffmpeg_path_subdir}")
            return os.path.abspath(bundled_ffmpeg_path_subdir)

        # Check in main directory of the bundle (less common for dedicated ffmpeg folder)
        bundled_ffmpeg_path_maindir = os.path.join(bundle_dir, ffmpeg_name)
        print(f"Checking for bundled ffmpeg at: {bundled_ffmpeg_path_maindir}")
        if os.path.exists(bundled_ffmpeg_path_maindir) and os.access(bundled_ffmpeg_path_maindir, os.X_OK):
            print(f"Found bundled ffmpeg at: {bundled_ffmpeg_path_maindir}")
            return os.path.abspath(bundled_ffmpeg_path_maindir)

    # Fallback: Check system PATH
    print(f"Checking for ffmpeg in system PATH (shutil.which('ffmpeg'))...")
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        print(f"Found ffmpeg in PATH: {ffmpeg_in_path}")
        return os.path.abspath(ffmpeg_in_path)

    print("ffmpeg not found in bundled location or system PATH.")
    return None

FFMPEG_PATH = get_ffmpeg_path()
FFMPEG_AVAILABLE = FFMPEG_PATH is not None

if FFMPEG_AVAILABLE:
    print(f"FFmpeg is available. Path: {FFMPEG_PATH}")
else:
    print("FFmpeg is NOT available. The application may not function correctly for merging.")
# <<< MODIFIED/ADDED END >>>


# --- Core TTS Logic ---
async def get_voices_async():
    """Asynchronously fetches the list of available voices."""
    try:
        voices = await edge_tts.list_voices()
        return sorted(voices, key=lambda v: v['ShortName'])
    except Exception as e:
        print(f"Error fetching voices: {e}")
        return []

async def text_to_speech_async(text, voice_short_name, output_file):
    """
    Asynchronously converts a single text chunk to speech and saves to a file.
    Returns (success_boolean, error_message_or_None, duration_or_None).
    """
    if not text or text.isspace():
        return True, None, 0.0 # Success, no error, zero duration for empty chunk
    start_time = time.monotonic()
    try:
        communicate = edge_tts.Communicate(text, voice_short_name)
        await communicate.save(output_file)
        end_time = time.monotonic()
        duration = end_time - start_time
        return True, None, duration
    except Exception as e:
        end_time = time.monotonic()
        # duration = end_time - start_time # Record duration even on failure for analysis? Maybe not useful.
        error_detail = f"Text length: {len(text)}, Error: {e}"
        print(f"Error during TTS conversion for a chunk: {error_detail}")
        return False, str(e), None # Failed, return error and None duration


# --- Text Processing ---
def split_text_simple(text, max_length=TEXT_CHUNK_SIZE):
    """
    Splits text into chunks: by paragraphs (\n\n),
    then by max_length if a paragraph is too long.
    Filters out empty chunks. Tries to split at sentence ends.
    """
    chunks = []
    if not text: return chunks
    paragraphs = text.split('\n\n')
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph: continue
        if len(paragraph) <= max_length:
            chunks.append(paragraph)
        else:
            start = 0
            while start < len(paragraph):
                end = start + max_length
                best_break = -1
                # Try to find sentence endings (., ?, !) within a reasonable range
                # Look slightly beyond max_length to catch sentences that just cross the boundary
                for punct in ['.', '?', '!']:
                    # Search range: from start up to end + a small buffer (e.g., 50 chars)
                    # Ensure search range does not exceed paragraph length
                    p_break = paragraph.rfind(punct, start, min(end + 50, len(paragraph)))
                    if p_break != -1 and p_break > start: # Found a punctuation
                        # Check if it's a valid sentence end (followed by space or end of paragraph)
                        if (p_break + 1 == len(paragraph) or
                            (p_break + 1 < len(paragraph) and paragraph[p_break + 1].isspace())):
                            # Avoid splitting common abbreviations like "Mr." or "U.S."
                            # This is a heuristic: check if char before period is part of an initialism (e.g., U.S.A.)
                            # or an honorific (e.g. Mr. Dr.)
                            if p_break > start + 2 and paragraph[p_break-2:p_break].isalpha() and paragraph[p_break-2].isupper():
                                # Example: "U.S." - don't break after "S." if "U" is uppercase
                                # This is not foolproof but helps in some cases.
                                continue # Skip this break, likely part of an abbreviation
                            best_break = max(best_break, p_break)

                if best_break != -1:
                    end = best_break + 1 # Include the punctuation in the current chunk
                elif end >= len(paragraph): # If no good break found and we are at the end
                    end = len(paragraph)
                # If no sentence break found and chunk is still too long, just split at max_length
                # (This is implicitly handled by `end = start + max_length` if best_break remains -1)

                chunk = paragraph[start:end].strip()
                if chunk: chunks.append(chunk)
                start = end

    final_chunks = [chunk for chunk in chunks if chunk] # Ensure no empty strings from strip
    print(f"Split text into {len(final_chunks)} non-empty chunks.")
    if not final_chunks and text.strip(): # If input text was not empty but splitting yielded nothing
        print("Warning: Text splitting resulted in zero chunks despite non-empty input. Processing as one chunk.")
        return [text.strip()] # Return the whole text as one chunk
    return final_chunks


# --- GUI Class ---
class EdgeTTS_GUI:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Edge TTS Converter (FFmpeg Merge, Concurrency: {MAX_CONCURRENT_TASKS})")
        self.root.minsize(650, 450)
        self.root.resizable(True, True)

        # <<< MODIFIED/ADDED START >>>
        # --- Critical Dependency Check for FFmpeg ---
        if not FFMPEG_AVAILABLE:
            # Display a more informative error message if FFmpeg is not found
            messagebox.showerror("Dependency Error",
                                 "ffmpeg was not found bundled with the application or in your system's PATH.\n\n"
                                 "This application requires ffmpeg for merging audio chunks efficiently.\n\n"
                                 "If you installed this application, please try re-downloading or re-installing it. "
                                 "If you are running from source, please install ffmpeg "
                                 "(e.g., via Homebrew, Chocolatey, or from the official ffmpeg.org website) "
                                 "and ensure it's added to your system's PATH or placed in a 'ffmpeg' subdirectory "
                                 "next to this script/executable.")
            # It's important to allow the GUI to initialize enough for the messagebox to show
            # then schedule the destruction.
            self.root.after(100, self.root.destroy)
            return # Stop further initialization of the GUI
        # <<< MODIFIED/ADDED END >>>

        # --- Member Variables ---
        self.all_voices = []
        self.input_file_path = tk.StringVar()
        self.selected_voice = tk.StringVar()
        self.status_text = tk.StringVar(value="Status: Initializing...")
        self.filter_multilingual = tk.BooleanVar(value=False)
        self.progress_var = tk.DoubleVar(value=0.0)
        self.merge_progress_var = tk.DoubleVar(value=0.0)
        self.eta_text = tk.StringVar(value="ETA: Calculating...")

        self.conversion_start_time = None
        self.total_chunks = 0
        self.completed_chunks = 0
        self.chunk_times = []
        self.is_converting = False
        self.closing = False
        self.gui_queue = queue.Queue()

        # --- Style ---
        style = ttk.Style(self.root)
        style.theme_use('clam') # Or 'alt', 'default', 'classic'
        style.configure("TButton", padding=6, relief="flat", background="#ccc")
        style.configure("TLabel", padding=5)
        style.configure("TCombobox", padding=5)
        style.configure("Status.TLabel", foreground="grey")
        style.configure("TCheckbutton", padding=5)
        style.configure("ETA.TLabel", padding=(5,0), foreground="navy")
        style.configure("Merge.Horizontal.TProgressbar", troughcolor ='#E0E0E0', background='#4CAF50') # Green for merge

        # --- UI Elements ---
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)
        main_frame.columnconfigure(1, weight=1) # Allow middle column (entry) to expand

        # Input File Row
        ttk.Label(main_frame, text="Input Text File (.txt):").grid(row=0, column=0, sticky=tk.W, pady=(0, 10), padx=(0,5))
        self.file_entry = ttk.Entry(main_frame, textvariable=self.input_file_path, state="readonly")
        self.file_entry.grid(row=0, column=1, sticky=tk.EW, pady=(0, 10), padx=(0,5))
        self.browse_button = ttk.Button(main_frame, text="Browse...", command=self.browse_file)
        self.browse_button.grid(row=0, column=2, sticky=tk.E, pady=(0, 10))

        # Voice Selection Row
        ttk.Label(main_frame, text="Select Voice:").grid(row=1, column=0, sticky=tk.W, pady=(0, 5), padx=(0,5))
        self.voice_combobox = ttk.Combobox(main_frame, textvariable=self.selected_voice, state="disabled", postcommand=self.filter_voices)
        self.voice_combobox.grid(row=1, column=1, columnspan=2, sticky=tk.EW, pady=(0, 5))
        self.voice_combobox.bind("<<ComboboxSelected>>", self.on_voice_select)

        # Filter Checkbox Row
        self.filter_checkbox = ttk.Checkbutton(
            main_frame, text="Show only Multilingual voices",
            variable=self.filter_multilingual, command=self.filter_voices
        )
        self.filter_checkbox.grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=(0, 15))

        # Convert Button Row
        self.convert_button = ttk.Button(main_frame, text="Convert to MP3", command=self.start_conversion_thread, state=tk.DISABLED)
        self.convert_button.grid(row=3, column=0, columnspan=3, pady=(10, 15))

        # TTS Progress Bar Row
        self.progressbar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100, mode='determinate')
        self.progressbar.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(5, 2), padx=(0,5))
        self.progressbar.grid_remove() # Hide initially

        # ETA Label Row (aligned right in last column)
        self.eta_label = ttk.Label(main_frame, textvariable=self.eta_text, style="ETA.TLabel", anchor=tk.E)
        self.eta_label.grid(row=4, column=2, sticky=tk.E, pady=(5, 2), padx=(5,0))
        self.eta_label.grid_remove() # Hide initially

        # Merge Progress Bar Row
        self.merge_progressbar = ttk.Progressbar(main_frame, variable=self.merge_progress_var, maximum=100, mode='determinate', style="Merge.Horizontal.TProgressbar")
        self.merge_progressbar.grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=(2, 5))
        self.merge_progressbar.grid_remove() # Hide initially

        # Status Bar Row
        self.status_label = ttk.Label(main_frame, textvariable=self.status_text, style="Status.TLabel", anchor=tk.W)
        self.status_label.grid(row=6, column=0, columnspan=3, sticky=tk.EW, pady=(5, 0))

        # --- Initial Setup ---
        self.update_status("Fetching available voices...")
        threading.Thread(target=self.load_voices_thread, daemon=True).start()
        self.root.after(QUEUE_CHECK_INTERVAL_MS, self.process_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)


    def on_close(self):
        """Handle window closing: set flag, destroy window."""
        if self.closing: return
        print("Closing application...")
        self.closing = True
        # Potentially wait for threads to finish here if needed, but daemon threads should exit.
        # Forcing destroy is usually okay for GUIs on user close.
        print("Destroying window...")
        try:
            self.root.destroy()
        except tk.TclError as e:
            print(f"Error destroying root window (might already be destroyed): {e}")


    def process_queue(self):
        """Processes messages from the background thread queue."""
        if self.closing: return

        try:
            while True: # Process all messages currently in queue
                message = self.gui_queue.get_nowait()
                msg_type = message[0]
                payload = message[1] if len(message) > 1 else None

                if not self.root.winfo_exists(): # Window might have been closed
                    self.closing = True; break

                if msg_type == 'voices_loaded':
                    self.all_voices = payload
                    if self.all_voices:
                        self.filter_voices() # This will populate and set initial state
                        self.update_status("Voices loaded. Ready.")
                    else:
                        self.update_status("Failed to load voices. Check console/connection.")
                        messagebox.showerror("Voice Fetch Error", "Could not fetch voices. Check internet connection and restart.")
                        if self.voice_combobox.winfo_exists(): self.voice_combobox.config(state="disabled")
                elif msg_type == 'progress_update': # TTS Chunk progress with duration
                    chunk_duration = payload
                    self.completed_chunks += 1
                    if chunk_duration is not None and chunk_duration > 0: # Only store valid positive durations
                        self.chunk_times.append(chunk_duration)
                    self.update_progress_display(self.completed_chunks, self.total_chunks)
                elif msg_type == 'merge_prep_progress':
                    current, total = payload[0], payload[1]
                    self.update_merge_progress_display(current, total)
                elif msg_type == 'show_merge_progress': # Message to show merge bar
                    if self.merge_progressbar.winfo_exists(): self.merge_progressbar.grid()
                elif msg_type == 'status':
                    self.update_status(payload)
                elif msg_type == 'success':
                    self.conversion_success(payload)
                elif msg_type == 'error':
                    self.conversion_error(payload)
                elif msg_type == 'reset_ui':
                    self.reset_ui_state()
                else:
                    print(f"Unknown queue message type: {msg_type}")

        except queue.Empty:
            pass # No messages in queue, normal
        except tk.TclError as e: # Window might be destroyed during processing
            self.closing = True
            print(f"TclError in process_queue (window likely destroyed): {e}")
        except Exception as e:
            print(f"Error processing queue: {e}")
            # Potentially log this error more formally

        if not self.closing:
            self.root.after(QUEUE_CHECK_INTERVAL_MS, self.process_queue)


    def update_status(self, message):
        """Safely updates the status bar text."""
        try:
            if self.status_label.winfo_exists(): # Check if widget still exists
                self.status_text.set(f"Status: {message}")
        except tk.TclError:
            pass # Widget might have been destroyed


    def format_time_delta(self, seconds):
        """Formats seconds into HH:MM:SS."""
        if seconds < 0: seconds = 0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02}:{minutes:02}:{secs:02}"


    def update_progress_display(self, current_completed, total_chunks):
        """Safely updates TTS progress bar and ETA with CI."""
        if total_chunks == 0 or not self.root.winfo_exists(): return

        try:
            # --- Update Progress Bar ---
            current_completed = min(current_completed, total_chunks) # Cap at total
            progress_percentage = (current_completed / total_chunks) * 100
            if self.progressbar.winfo_exists():
                self.progress_var.set(progress_percentage)

            # --- Calculate ETA and CI ---
            eta_str = "ETA: Calculating..."
            if self.conversion_start_time and current_completed > 0 and current_completed < total_chunks:
                remaining_chunks = total_chunks - current_completed
                n_times = len(self.chunk_times)

                if n_times > 0: # Need at least one successful chunk time
                    # Calculate mean time per chunk
                    mean_time_per_chunk = statistics.mean(self.chunk_times)

                    # Estimate total remaining time based on mean, adjusted for concurrency
                    # This assumes tasks are processed in parallel up to MAX_CONCURRENT_TASKS
                    # A more accurate ETA would consider the current number of active tasks,
                    # but this is a reasonable approximation.
                    effective_remaining_time = (mean_time_per_chunk * remaining_chunks) / MAX_CONCURRENT_TASKS
                    eta_str = f"ETA: {self.format_time_delta(effective_remaining_time)}"

                    # Calculate Confidence Interval (needs at least 2 samples for stdev)
                    if n_times > 1:
                        std_dev_time_per_chunk = statistics.stdev(self.chunk_times)
                        # Estimate std dev for the *total* remaining time, considering concurrency
                        # This is a heuristic: variance adds, so std dev scales with sqrt(N_remaining_effective_sequential_tasks)
                        # Effective number of sequential "slots" remaining is remaining_chunks / MAX_CONCURRENT_TASKS
                        effective_sequential_slots = math.ceil(remaining_chunks / MAX_CONCURRENT_TASKS)
                        std_dev_total_remaining_heuristic = std_dev_time_per_chunk * math.sqrt(effective_sequential_slots)

                        margin_of_error_seconds = CI_Z_SCORE * std_dev_total_remaining_heuristic
                        margin_str = self.format_time_delta(margin_of_error_seconds)
                        eta_str += f" (± {margin_str})"
                # else: Not enough data yet for mean calculation, keep "Calculating..."

            elif current_completed == 0 and self.is_converting:
                eta_str = "ETA: Starting..."
            elif current_completed == total_chunks and self.is_converting: # All TTS chunks done
                eta_str = "ETA: Finalizing..." # TTS done, waiting for merge/cleanup

            # --- Update UI ---
            if self.eta_label.winfo_exists():
                self.eta_text.set(eta_str)

            current_status = self.status_text.get()
            if self.status_label.winfo_exists() and ("Processing" in current_status or "Starting" in current_status or "Calculating" in current_status):
                self.status_text.set(f"Status: Processing TTS chunk {current_completed}/{total_chunks} ({progress_percentage:.1f}%)")

        except tk.TclError: pass # Widget might be destroyed
        except Exception as e:
            print(f"Error updating progress display: {e}")


    def update_merge_progress_display(self, current_file, total_files):
        """Safely updates the merge preparation progress bar."""
        if total_files == 0 or not self.root.winfo_exists(): return
        try:
            progress_percentage = (current_file / total_files) * 100
            if self.merge_progressbar.winfo_exists():
                # Ensure merge bar is visible when updating its progress
                if not self.merge_progressbar.winfo_ismapped(): # Check if it's currently hidden
                    self.merge_progressbar.grid()
                self.merge_progress_var.set(progress_percentage)
            self.update_status(f"Preparing merge: File {current_file}/{total_files} ({progress_percentage:.1f}%)")
        except tk.TclError: pass
        except Exception as e:
            print(f"Error updating merge progress display: {e}")


    def load_voices_thread(self):
        """Loads voices in background and puts result onto the queue."""
        if not hasattr(self, 'gui_queue'): return # Safety check if called too early or late
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        voices = []
        try:
            voices = loop.run_until_complete(get_voices_async())
            if not self.closing: self.gui_queue.put(('voices_loaded', voices))
        except Exception as e:
            print(f"Error in load_voices thread: {e}")
            if not self.closing: self.gui_queue.put(('voices_loaded', [])) # Send empty list on error
        finally:
            loop.close()


    def filter_voices(self):
        """Filters voices based on checkbox and populates combobox."""
        if not self.all_voices or not self.root.winfo_exists(): return
        try:
            current_selection_display_name = self.selected_voice.get() # Get current display name
            apply_filter = self.filter_multilingual.get()

            filtered_voice_list = [
                v for v in self.all_voices
                if not apply_filter or "Multilingual" in v.get('FriendlyName', v['ShortName']) # Prefer FriendlyName for filter
            ]
            voice_display_names = [
                f"{v['ShortName']} ({v.get('Gender', 'N/A')}, {v.get('Locale', 'N/A')})"
                for v in filtered_voice_list
            ]
            self.populate_voice_combobox(voice_display_names, current_selection_display_name)

            if not self.is_converting: # Only update status if not in middle of conversion
                status_msg = "Showing all voices."
                if apply_filter: status_msg = "Showing Multilingual voices."
                if not voice_display_names:
                    status_msg = "No voices match filter." if self.all_voices else "Voice list empty."
                self.update_status(status_msg)
        except tk.TclError as e:
            print(f"TclError in filter_voices: {e}") # Window might be closing


    def populate_voice_combobox(self, voice_names, previous_selection_display_name):
        """Populates the voice combobox and tries to preserve selection."""
        if not self.root.winfo_exists() or not self.voice_combobox.winfo_exists(): return
        try:
            self.voice_combobox['values'] = voice_names
            if voice_names:
                if previous_selection_display_name in voice_names:
                    self.selected_voice.set(previous_selection_display_name)
                    # self.voice_combobox.set(previous_selection_display_name) # Setting textvariable is enough
                else:
                    self.selected_voice.set(voice_names[0]) # Default to first if previous not in new list
                    # self.voice_combobox.current(0)
                # Combobox state depends on whether conversion is active
                self.voice_combobox.config(state="readonly" if not self.is_converting else "disabled")
            else: # No voices to display
                self.selected_voice.set("")
                self.voice_combobox.set("") # Clear visual selection
                self.voice_combobox.config(state="disabled")
            self.check_conversion_ready()
        except tk.TclError as e:
            print(f"TclError in populate_voice_combobox: {e}")


    def browse_file(self):
        """Opens file dialog to select input text file."""
        if self.is_converting or self.closing: return
        try:
            filepath = filedialog.askopenfilename(
                title="Select Text File",
                filetypes=(("Text files", "*.txt"), ("All files", "*.*"))
            )
            if filepath:
                self.input_file_path.set(filepath)
                self.update_status("Input file selected.")
                self.check_conversion_ready()
            elif not self.input_file_path.get(): # If dialog cancelled and no path was previously set
                self.update_status("File selection cancelled.")
        except Exception as e:
            print(f"Error during file browse: {e}")
            self.update_status("Error browsing file.")


    def on_voice_select(self, event=None):
        """Handles voice selection from combobox."""
        if self.is_converting or self.closing: return
        try:
            selected_val = self.selected_voice.get()
            if selected_val: # selected_val is the display name like "en-US-JennyNeural (Female, en-US)"
                # Extract ShortName for status update if needed, or just use display name
                self.update_status(f"Voice selected: {selected_val.split(' ')[0]}")
            self.check_conversion_ready()
        except tk.TclError as e: # Window might be closing
            print(f"TclError on voice select: {e}")


    def check_conversion_ready(self):
        """Enables/disables convert button based on input and voice selection."""
        if self.closing or not self.root.winfo_exists() or not self.convert_button.winfo_exists(): return
        try:
            # Conversion is ready if a file is selected, a voice is selected, and not currently converting
            is_ready = (
                self.input_file_path.get() and
                self.selected_voice.get() and
                not self.is_converting
            )
            self.convert_button.config(state=tk.NORMAL if is_ready else tk.DISABLED)
        except tk.TclError as e:
            print(f"TclError checking conversion ready state: {e}")


    def start_conversion_thread(self):
        """Prepares and starts the concurrent TTS conversion in a separate thread."""
        if self.is_converting or self.closing: return

        input_path = self.input_file_path.get()
        selected_display_name = self.selected_voice.get() # This is "ShortName (Gender, Locale)"

        if not input_path or not selected_display_name:
            messagebox.showwarning("Missing Input", "Please select both an input file and a voice.")
            return

        # Find the actual voice_short_name from the selected_display_name
        voice_short_name = None
        for voice in self.all_voices:
            # Construct the display name as it appears in the combobox to match
            current_voice_display_name = f"{voice['ShortName']} ({voice.get('Gender', 'N/A')}, {voice.get('Locale', 'N/A')})"
            if current_voice_display_name == selected_display_name:
                voice_short_name = voice['ShortName']
                break

        if not voice_short_name:
            messagebox.showerror("Voice Error", f"Selected voice details not found for '{selected_display_name}'. This might indicate an internal error or outdated voice list. Please try reselecting or restarting.")
            self.update_status("Error finding selected voice details.")
            return

        # Suggest output filename
        default_output_name = os.path.splitext(os.path.basename(input_path))[0] + ".mp3"
        output_file = filedialog.asksaveasfilename(
            title="Save MP3 As...",
            defaultextension=".mp3",
            initialfile=default_output_name,
            filetypes=(("MP3 audio files", "*.mp3"), ("All files", "*.*"))
        )
        if not output_file:
            self.update_status("Save cancelled.")
            return

        self.update_status("Reading and chunking input file...")
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                text_content = f.read()
            if not text_content.strip():
                messagebox.showwarning("Empty File", "The selected text file is empty.")
                self.update_status("Empty file selected."); return
            text_chunks = split_text_simple(text_content)
            if not text_chunks: # split_text_simple should now handle this and return [original_text]
                messagebox.showwarning("Empty Content", "Could not extract any text chunks from the file. This shouldn't happen if the file has text.")
                self.update_status("No text content found after splitting."); return

            self.total_chunks = len(text_chunks)
            self.completed_chunks = 0
            self.chunk_times = [] # Reset chunk times list for new conversion
            print(f"Ready to process {self.total_chunks} chunks concurrently (max {MAX_CONCURRENT_TASKS}).")

        except FileNotFoundError:
            messagebox.showerror("File Error", f"Input file not found:\n{input_path}")
            self.update_status("File not found."); return
        except Exception as e:
            messagebox.showerror("Read Error", f"Error reading or chunking input file:\n{e}")
            self.update_status("Error reading file."); return

        # --- UI updates before starting thread ---
        try:
            self.is_converting = True
            self.convert_button.config(state=tk.DISABLED)
            self.browse_button.config(state=tk.DISABLED)
            self.voice_combobox.config(state=tk.DISABLED)
            self.filter_checkbox.config(state=tk.DISABLED)

            self.progressbar.grid(); self.merge_progressbar.grid_remove(); self.eta_label.grid() # Show TTS progress, hide merge, show ETA
            self.progress_var.set(0); self.merge_progress_var.set(0)
            self.eta_text.set("ETA: Starting...")
            self.update_status("Starting conversion...")
            self.conversion_start_time = time.monotonic() # Use monotonic for duration calculation
        except tk.TclError as e: # Window might be closing
            print(f"TclError preparing UI for conversion: {e}")
            self.is_converting = False # Rollback state
            self.reset_ui_state() # Attempt to reset UI
            return

        # --- Start the conversion in a new thread ---
        threading.Thread(
            target=self.run_conversion_wrapper,
            args=(text_chunks, voice_short_name, output_file),
            daemon=True
        ).start()


    def run_conversion_wrapper(self, text_chunks, voice, final_output_file):
        """Wrapper to run the async conversion logic in a separate thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            if self.closing: return # Check if app is closing before starting async task
            loop.run_until_complete(self.run_conversion_concurrent_ffmpeg(text_chunks, voice, final_output_file))
        except Exception as e:
            # This catches errors from within run_conversion_concurrent_ffmpeg if they aren't caught there,
            # or errors from setting up the loop/running it.
            print(f"Error in async conversion wrapper: {e}")
            if not self.closing: # Only update GUI if not already shutting down
                self.gui_queue.put(('error', f"Unexpected async error: {e}"))
                self.gui_queue.put(('reset_ui', None)) # Ensure UI is reset on unexpected error
        finally:
            loop.close()


    async def run_conversion_concurrent_ffmpeg(self, text_chunks, voice, final_output_file):
        """
        Runs TTS conversion concurrently, then merges using ffmpeg concat demuxer.
        """
        if self.closing: return

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
        tasks = []
        # Store tuples: (index, temp_path_or_None, error_msg_or_None, duration_or_None)
        # Initialize with None for paths and errors
        results_data = [(i, None, None, None) for i in range(len(text_chunks))]
        temp_file_paths_to_clean = [] # Keep track of all temp files created

        async def process_single_chunk(index, chunk_text):
            """Helper coroutine to process one chunk with semaphore control."""
            nonlocal results_data, temp_file_paths_to_clean # Allow modification of these outer scope variables
            if self.closing: return False, None # Return success status and duration

            temp_path = None
            duration = None
            success = False
            error_msg = None
            try:
                # Create a temporary file for this chunk's audio
                # delete=False is important as edge_tts needs to write to it, and we need it for ffmpeg
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_chunk_file:
                    temp_path = temp_chunk_file.name
                temp_file_paths_to_clean.append(temp_path) # Add to cleanup list immediately

                async with semaphore: # Acquire semaphore before TTS call
                    if self.closing: # Re-check closing status after acquiring semaphore
                        results_data[index] = (index, None, "Cancelled during semaphore wait", None)
                        return False, None

                    success, error_msg, duration = await text_to_speech_async(chunk_text, voice, temp_path)
                    results_data[index] = (index, temp_path if success else None, error_msg, duration)

                    if not self.closing:
                        # Send progress update to GUI queue (duration might be None if error occurred)
                        self.gui_queue.put(('progress_update', duration))
                    return success, duration # Return success and duration for this chunk

            except Exception as e:
                print(f"Critical error processing chunk {index+1} (before TTS call or during temp file handling): {e}")
                error_msg = str(e)
                results_data[index] = (index, None, error_msg, None) # Record error
                # If temp_path was created but error occurred before TTS or during cleanup of this specific path
                if temp_path and temp_path in temp_file_paths_to_clean: temp_file_paths_to_clean.remove(temp_path)
                if temp_path and os.path.exists(temp_path):
                    try: os.remove(temp_path) # Attempt to clean up this specific temp file
                    except Exception as rm_err: print(f"Could not remove temp file {temp_path} after error: {rm_err}")

                if not self.closing:
                    self.gui_queue.put(('progress_update', None)) # Still signal progress, but no duration
                return False, None # Indicate failure for this chunk

        # --- Create and schedule all TTS tasks ---
        for i, chunk in enumerate(text_chunks):
            if self.closing: break
            tasks.append(asyncio.create_task(process_single_chunk(i, chunk)))

        if self.closing: # If closing was triggered while creating tasks
            # Cancel any created tasks (though they should self-terminate if they check self.closing)
            for task in tasks: task.cancel()
            # Clean up any temp files created so far
            self._cleanup_temp_files(temp_file_paths_to_clean)
            if not self.closing: self.gui_queue.put(('reset_ui', None)) # Should not be reached if self.closing is true
            return

        if not tasks: # Should only happen if text_chunks was empty, handled earlier
            print("No conversion tasks were created.")
            if not self.closing: self.gui_queue.put(('reset_ui', None))
            self._cleanup_temp_files(temp_file_paths_to_clean) # Still cleanup
            return

        # Wait for all TTS tasks to complete
        # Using return_exceptions=False because process_single_chunk handles its own errors
        # and records them in results_data. We don't want gather to stop on first error.
        await asyncio.gather(*tasks, return_exceptions=False)

        if self.closing: # Check if closing was triggered during TTS tasks
            self._cleanup_temp_files(temp_file_paths_to_clean)
            # No need to reset UI if closing
            return

        # --- Process results and Prepare for Merge (only if not closing) ---
        first_error_message_for_user = None
        successful_temp_files_ordered = [None] * len(text_chunks) # Pre-allocate list for correct order
        all_tts_chunks_succeeded = True

        # Collect results, check for errors, and populate successful_temp_files_ordered
        for idx, file_path_or_none, error_msg_from_chunk, _duration in results_data:
            if error_msg_from_chunk:
                all_tts_chunks_succeeded = False
                if not first_error_message_for_user: # Store the first error encountered
                    first_error_message_for_user = f"Chunk {idx+1} failed: {error_msg_from_chunk}"
                print(f"TTS Error for chunk {idx+1}: {error_msg_from_chunk}")
            elif file_path_or_none:
                # Ensure the file exists and is not empty before considering it successful
                if os.path.exists(file_path_or_none) and os.path.getsize(file_path_or_none) > 0:
                    successful_temp_files_ordered[idx] = file_path_or_none
                else:
                    all_tts_chunks_succeeded = False
                    missing_file_error = f"Chunk {idx+1} TTS reported success, but temp file '{file_path_or_none}' is missing or empty."
                    print(f"Warning: {missing_file_error}")
                    if not first_error_message_for_user:
                        first_error_message_for_user = missing_file_error
                    # Ensure this failed path is not used for merge
                    if file_path_or_none in temp_file_paths_to_clean and os.path.exists(file_path_or_none):
                        # It exists but is empty, or other issue. Mark for cleanup but don't use.
                        pass
                    elif file_path_or_none in temp_file_paths_to_clean and not os.path.exists(file_path_or_none):
                        # Path was in cleanup list but file doesn't exist, already handled.
                        pass

            # If file_path_or_none is None and no error_msg, it means an empty input chunk, which is fine.

        # Filter out None entries from successful_temp_files_ordered to get the actual list of files to merge
        valid_files_to_merge = [f for f in successful_temp_files_ordered if f is not None]

        # --- Merge using ffmpeg ---
        merge_was_successful = False
        if all_tts_chunks_succeeded and valid_files_to_merge:
            if not self.closing:
                # <<< MODIFIED/ADDED START >>>
                if not FFMPEG_PATH: # Critical check before attempting to use ffmpeg
                    error_msg = "ffmpeg path could not be determined. Cannot merge audio."
                    print(error_msg)
                    if not self.closing:
                        self.gui_queue.put(('error', error_msg))
                    # No reset_ui here, it's handled at the end of this function
                    self._cleanup_temp_files(temp_file_paths_to_clean)
                    if not self.closing: self.gui_queue.put(('reset_ui', None))
                    return # Cannot proceed with merge
                # <<< MODIFIED/ADDED END >>>

                if self.root.winfo_exists(): # Check if GUI is still there
                    self.gui_queue.put(('show_merge_progress', None)) # Tell GUI to show merge bar
                    self.gui_queue.put(('status', "Preparing file list for ffmpeg merge..."))

            list_file_path = None # Path to the temporary file listing chunks for ffmpeg
            try:
                # Create a temporary file to list the audio chunks for ffmpeg's concat demuxer
                with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False, encoding='utf-8') as list_file:
                    list_file_path = list_file.name
                    total_files_for_list = len(valid_files_to_merge)
                    for i, temp_audio_file_path in enumerate(valid_files_to_merge):
                        # ffmpeg requires paths to be escaped, especially if they contain spaces or special characters.
                        # Using absolute paths is safer.
                        abs_path = os.path.abspath(temp_audio_file_path)
                        # Simple escaping for paths in ffmpeg file list:
                        # Replace single quotes with '\'' (quote, backslash, quote, quote)
                        # This is a common way to handle paths with single quotes for shell-like processing.
                        # However, for ffmpeg's concat demuxer, paths should be 'safe'.
                        # The -safe 0 option for ffmpeg concat demuxer allows any filename,
                        # but paths in the list file still need to be correct.
                        # Let's ensure paths are written carefully.
                        # For Windows, paths with spaces don't need extra quotes if -safe 0 is used.
                        # For Unix-like, paths with spaces or special chars might need care.
                        # The `file 'path'` syntax in concat demuxer list is generally robust.
                        list_file.write(f"file '{abs_path}'\n")
                        if not self.closing:
                            self.gui_queue.put(('merge_prep_progress', (i + 1, total_files_for_list)))
                print(f"Generated ffmpeg list file: {list_file_path} with {len(valid_files_to_merge)} files.")

                # <<< MODIFIED/ADDED START >>>
                # Use the globally determined FFMPEG_PATH
                ffmpeg_cmd = [
                    FFMPEG_PATH,      # Use the detected path to ffmpeg
                    "-f", "concat",
                    "-safe", "0",     # Allows any filename in the list file (use with caution if paths are untrusted)
                    "-i", list_file_path,
                    "-c", "copy",     # Copy audio codec, no re-encoding
                    "-y",             # Overwrite output file if it exists
                    final_output_file
                ]
                # <<< MODIFIED/ADDED END >>>

                print(f"Running ffmpeg command: {' '.join(ffmpeg_cmd)}")
                if not self.closing: self.gui_queue.put(('status', "Merging audio with ffmpeg (this should be fast)..."))

                # Determine creationflags for subprocess based on platform to hide console window
                creation_flags = 0
                if sys.platform == 'win32':
                    creation_flags = subprocess.CREATE_NO_WINDOW # 0x08000000

                # Start ffmpeg process
                process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE, # Capture stdout
                    stderr=subprocess.PIPE, # Capture stderr
                    text=True,              # Decode stdout/stderr as text
                    creationflags=creation_flags
                )
                # Communicate with process (wait for completion and get output)
                # Add a timeout to prevent indefinite blocking if ffmpeg hangs
                try:
                    stdout, stderr = process.communicate(timeout=120) # 2 minutes timeout
                except subprocess.TimeoutExpired:
                    process.kill() # Kill ffmpeg if it times out
                    stdout, stderr = process.communicate() # Try to get any output after kill
                    timeout_error_msg = "ffmpeg merge process timed out after 2 minutes."
                    print(f"Error: {timeout_error_msg}")
                    if not self.closing: self.gui_queue.put(('error', f"{timeout_error_msg}\nffmpeg stderr (if any):\n{stderr[:500]}..."))
                    # No 'success' or 'reset_ui' here, handled at the end

                if process.returncode == 0:
                    print("ffmpeg merge successful.")
                    merge_was_successful = True
                    if not self.closing: self.gui_queue.put(('success', final_output_file))
                else:
                    print(f"ffmpeg merge failed with return code {process.returncode}.")
                    print(f"ffmpeg stdout:\n{stdout}")
                    print(f"ffmpeg stderr:\n{stderr}")
                    if not self.closing:
                        # Provide a snippet of stderr as it often contains the crucial error info
                        self.gui_queue.put(('error', f"ffmpeg merge failed. Check console/log.\nError (from ffmpeg):\n{stderr[:500]}..."))

            except Exception as merge_prep_err:
                print(f"Error during ffmpeg preparation or execution: {merge_prep_err}")
                if not self.closing: self.gui_queue.put(('error', f"Error preparing or running merge: {merge_prep_err}"))
            finally:
                # Clean up the temporary list file for ffmpeg
                if list_file_path and os.path.exists(list_file_path):
                    try:
                        os.remove(list_file_path)
                        print(f"Cleaned up ffmpeg list file: {list_file_path}")
                    except Exception as list_clean_err:
                        print(f"Warning: Failed to clean up list file {list_file_path}: {list_clean_err}")
        elif not valid_files_to_merge and all_tts_chunks_succeeded: # All TTS succeeded but no files to merge (e.g. all input chunks were whitespace)
            print("TTS processing complete, but no valid audio data was generated to merge (e.g., input was all whitespace).")
            if not self.closing: self.gui_queue.put(('error', "No audio data generated from input. File might be empty or contain only whitespace."))
        else: # Some TTS chunks failed, or no valid files produced
            print(f"One or more TTS chunks failed or produced no valid output. Merge skipped. First error: {first_error_message_for_user}")
            if not self.closing:
                self.gui_queue.put(('error', first_error_message_for_user or "An unknown error occurred during chunk processing, or no audio was generated."))

        # --- Final Cleanup of all temporary audio chunk files ---
        self._cleanup_temp_files(temp_file_paths_to_clean)

        # --- Signal UI reset (only if not closing) ---
        # This ensures UI is reset regardless of success or failure of merge,
        # as long as the application isn't in the process of closing.
        if not self.closing:
            self.gui_queue.put(('reset_ui', None))


    def _cleanup_temp_files(self, temp_file_paths):
        """Helper method to clean up a list of temporary files."""
        print(f"Attempting to clean up {len(temp_file_paths)} temporary audio chunk files...")
        cleaned_count = 0
        for path in temp_file_paths:
            if path and os.path.exists(path): # Check if path is not None and file exists
                try:
                    os.remove(path)
                    cleaned_count += 1
                except Exception as cleanup_err:
                    print(f"Warning: Failed to clean up temp file {path}: {cleanup_err}")
        print(f"Successfully cleaned up {cleaned_count} temporary audio files.")


    def conversion_success(self, output_file):
        """Handles successful conversion (called from process_queue)."""
        if self.closing or not self.root.winfo_exists(): return
        try:
            # Merge progress bar might still be visible if merge was very fast
            if self.merge_progressbar.winfo_exists(): self.merge_progressbar.grid_remove()
            self.update_status(f"Success! Saved to {os.path.basename(output_file)}")
            messagebox.showinfo("Success", f"Audio successfully saved to:\n{output_file}")
        except tk.TclError as e:
            print(f"TclError showing success message: {e}") # Window might be closing


    def conversion_error(self, error_message):
        """Handles conversion errors (called from process_queue)."""
        if self.closing or not self.root.winfo_exists(): return
        try:
            if self.merge_progressbar.winfo_exists(): self.merge_progressbar.grid_remove()
            self.update_status(f"Error during conversion.") # General status
            # Ensure error_message is a string and truncate for display
            display_error = str(error_message)
            if len(display_error) > 300: display_error = display_error[:300] + '...'
            messagebox.showerror("Conversion Error", f"Failed to convert text to speech or merge files.\n\nDetails: {display_error}")
        except tk.TclError as e:
            print(f"TclError showing error message: {e}")


    def reset_ui_state(self):
        """Resets buttons, progress bars, etc. (called from process_queue)."""
        if self.closing or not self.root.winfo_exists(): return
        print("Resetting UI state...")
        self.is_converting = False
        try:
            # Hide progress elements
            if self.progressbar.winfo_exists(): self.progressbar.grid_remove()
            if self.merge_progressbar.winfo_exists(): self.merge_progressbar.grid_remove()
            if self.eta_label.winfo_exists(): self.eta_label.grid_remove()

            # Reset progress variables
            self.progress_var.set(0); self.merge_progress_var.set(0)
            self.eta_text.set("ETA: --:--:--") # Reset ETA text

            # Reset conversion tracking variables
            self.conversion_start_time = None
            self.total_chunks = 0; self.completed_chunks = 0
            self.chunk_times = [] # Clear chunk times list

            # Re-enable interactive elements
            if self.browse_button.winfo_exists(): self.browse_button.config(state=tk.NORMAL)
            if self.filter_checkbox.winfo_exists(): self.filter_checkbox.config(state=tk.NORMAL)
            if self.voice_combobox.winfo_exists():
                # Enable combobox if voices are loaded, otherwise keep disabled
                self.voice_combobox.config(state="readonly" if self.voice_combobox['values'] else "disabled")

            # Update convert button state (might become enabled if inputs are valid)
            self.check_conversion_ready()

            # Update status message if not already showing a success/error from this operation
            current_status = self.status_text.get()
            if "Success!" not in current_status and "Error" not in current_status:
                status_msg = "Ready." if self.all_voices else "Failed to load voices. Restart recommended."
                self.update_status(status_msg)

        except tk.TclError as e:
            print(f"TclError during UI reset (window likely closing): {e}")
        except Exception as e:
            print(f"Unexpected error during UI reset: {e}")


# --- Main Execution ---
if __name__ == "__main__":
    # On Windows, for Tkinter with asyncio, ProactorEventLoop can cause issues.
    # WindowsSelectorEventLoopPolicy is generally preferred.
    if os.name == 'nt': # Check if running on Windows
        try:
            # Only set policy if not already a Proactor (or if default is not Selector)
            # This check might be too simplistic; usually, it's safe to just set it.
            if not isinstance(asyncio.get_event_loop_policy().get_event_loop(), asyncio.ProactorEventLoop):
                 asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                 print("Set asyncio policy to WindowsSelectorEventLoopPolicy for Windows.")
            else:
                print("Asyncio event loop is ProactorEventLoop or already compatible; not changing policy.")
        except Exception as policy_err:
            print(f"Could not set asyncio event loop policy for Windows: {policy_err}")

    app_root = tk.Tk()
    gui_instance = None # To hold the GUI instance

    # <<< MODIFIED/ADDED START >>>
    # The FFMPEG_AVAILABLE check is now done inside EdgeTTS_GUI.__init__
    # This allows the Tkinter window to be created first, so messageboxes can be shown
    # before potentially destroying the root window.
    # The initial FFMPEG_PATH and FFMPEG_AVAILABLE are determined at the script's top level.
    # If FFMPEG_AVAILABLE is False here, the GUI's __init__ will handle the error message and exit.
    # <<< MODIFIED/ADDED END >>>

    try:
        gui_instance = EdgeTTS_GUI(app_root)
        # Check if GUI initialization was aborted (e.g., due to missing FFMPEG)
        # A simple way is to see if a core widget exists, or if a flag was set in __init__
        # For now, we assume if __init__ returned, it's either okay or has scheduled its own destruction.
        # A more robust check might involve a flag set by __init__ upon successful completion.
        if not app_root.winfo_exists(): # If root was destroyed by __init__ (e.g. FFMPEG error)
            print("GUI initialization aborted (e.g., FFMPEG not found). Exiting.")
            gui_instance = None # Ensure it's None so mainloop isn't called

    except Exception as gui_init_error:
        print(f"Fatal error initializing GUI: {gui_init_error}")
        try:
            # Attempt to show a messagebox even if GUI init failed partially
            messagebox.showerror("GUI Initialization Error", f"Failed to initialize the application window:\n{gui_init_error}")
        except tk.TclError: # If Tkinter itself is too broken for a messagebox
            pass # Just print to console
        if app_root.winfo_exists():
            app_root.destroy() # Clean up window if it exists
        gui_instance = None # Ensure it's None

    # Only run mainloop if the GUI instance was successfully created and window still exists
    if gui_instance and app_root.winfo_exists():
        try:
            print("Starting Tkinter mainloop...")
            app_root.mainloop()
            print("Tkinter mainloop finished.")
        except Exception as main_err:
            print(f"Unexpected error in Tkinter mainloop: {main_err}")
            # Try to show a final error message if possible
            try: messagebox.showerror("Fatal Application Error", f"An unexpected error occurred in the main application loop:\n{main_err}")
            except: pass # If Tkinter is too broken
    else:
        print("GUI not started or window destroyed before mainloop. Application will exit.")

    print("Application exiting.")
