# Testing & Debugging RataGUI with Claude Code on Windows 11

This guide explains how to set up your Windows 11 machine so that Claude Code can test, debug, and validate RataGUI — including FLIR cameras, NI-DAQmx triggers, video recording integrity, and GUI interaction.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Setup](#2-environment-setup)
3. [Testing FLIR Cameras](#3-testing-flir-cameras)
4. [Testing NI-DAQmx and Other Modules](#4-testing-ni-daqmx-and-other-modules)
5. [Verifying Recorded Videos](#5-verifying-recorded-videos)
6. [Testing GUI Buttons and Interaction](#6-testing-gui-buttons-and-interaction)
7. [Running the Full Test Suite](#7-running-the-full-test-suite)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Prerequisites

Install the following on your Windows 11 machine before starting:

| Software | Purpose | Download |
|----------|---------|----------|
| **Anaconda / Miniconda** | Python environment manager | https://docs.conda.io/en/latest/miniconda.html |
| **Git** | Version control | https://git-scm.com/download/win |
| **Claude Code** | AI-assisted development CLI | https://docs.anthropic.com/en/docs/claude-code |
| **FLIR Spinnaker SDK** | FLIR camera drivers + PySpin | https://www.flir.com/products/spinnaker-sdk/ |
| **NI-DAQmx Driver** | National Instruments hardware driver | https://www.ni.com/en/support/downloads/drivers/download.ni-daq-mx.html |
| **FFmpeg** | Video encoding/decoding | Installed via conda (recommended) or https://ffmpeg.org/download.html |
| **NVIDIA GPU Driver** (optional) | GPU-accelerated video encoding | https://www.nvidia.com/download/index.aspx |

---

## 2. Environment Setup

### 2.1 Create the Conda Environment

Open **Anaconda Prompt** (or any terminal with conda available) and run:

```powershell
# CPU-only
conda create -n rataGUI ffmpeg pip scipy python=3.10
conda activate rataGUI

# OR GPU-enabled (if you have an NVIDIA GPU)
conda create -n rataGUI ffmpeg pip scipy python=3.10 cudnn=8.2 cudatoolkit=11.3 nvidia::cuda-nvcc=11.3
conda activate rataGUI
```

### 2.2 Install RataGUI in Development Mode

```powershell
cd path\to\rataGUI
python -m pip install -e ".[test]"
```

### 2.3 Install Hardware-Specific Packages

```powershell
# FLIR cameras — install the PySpin wheel from the Spinnaker SDK download
python -m pip install path\to\spinnaker_python-<version>-<system-info>.whl

# NI-DAQmx
python -m pip install nidaqmx

# Basler cameras (if applicable)
python -m pip install pypylon
```

> **Important:** After installing the Spinnaker SDK, restart your terminal (or reboot) so that environment variables take effect.

### 2.4 Verify the Installation

```powershell
conda activate rataGUI
python -c "import rataGUI; print(rataGUI.__version__)"
python -c "import PySpin; print('PySpin OK')"
python -c "import nidaqmx; print('nidaqmx OK')"
ffmpeg -version
```

### 2.5 Launch Claude Code

Open a terminal in the rataGUI project directory and start Claude Code:

```powershell
cd path\to\rataGUI
claude
```

Claude Code will have access to the project files, can run shell commands, and can execute Python scripts within your conda environment.

---

## 3. Testing FLIR Cameras

FLIR cameras are managed through `rataGUI/cameras/FLIRCamera.py`, which uses the PySpin (Spinnaker) SDK. Testing requires a physical FLIR camera connected via USB3 or GigE.

### 3.1 Camera Detection Test

Ask Claude Code to run this script to verify camera connectivity:

```
Run a Python script that imports PySpin, creates a System instance, lists all connected cameras by serial number, then releases the system.
```

Claude Code can execute:

```python
import PySpin

system = PySpin.System.GetInstance()
cam_list = system.GetCameras()
print(f"Found {cam_list.GetSize()} FLIR camera(s):")
for cam in cam_list:
    serial = cam.TLDevice.DeviceSerialNumber.ToString()
    model = cam.TLDevice.DeviceModelName.ToString()
    print(f"  Serial: {serial}, Model: {model}")
cam_list.Clear()
system.ReleaseInstance()
```

### 3.2 Frame Acquisition Test

Ask Claude Code to test acquiring frames from a specific camera:

```
Write and run a script that initializes FLIR camera <SERIAL_NUMBER>, acquires 100 frames,
reports the frame rate and any dropped frames, then closes the camera cleanly.
```

Key things Claude Code should verify:
- `initializeCamera()` returns `True`
- `readCamera()` returns `(True, frame)` with a valid numpy array
- Frame shape matches expected resolution (e.g., `(height, width, 3)` for RGB)
- `getMetadata()` returns incrementing `Camera Index` and `Frame Index`
- `frames_dropped` remains 0 under normal conditions
- `closeCamera()` completes without exceptions

### 3.3 Camera Configuration Test

Ask Claude Code to test different property configurations:

```
Test the FLIR camera with these settings and report if each applies successfully:
- Framerate: 60 fps
- Exposure: 5000 μs
- Gain: 10
- TriggerSource: Off
- Buffer Mode: OldestFirst
```

Claude Code can verify configuration by reading back property values from the camera node map after `initializeCamera()`.

### 3.4 Trigger Integration Test

If using an NI-DAQmx counter to drive the FLIR camera via hardware trigger:

```
Test FLIR camera with external triggering from NI counter at 30 fps on Line3.
Verify that frames arrive at the expected rate and no frames are dropped.
```

### 3.5 Automated Unit Tests

The existing test suite mocks PySpin so it can run without hardware:

```powershell
pytest tests/test_base_camera.py -v
```

To write integration tests that require a real camera, ask Claude Code:

```
Write a pytest integration test for FLIRCamera that connects to a real camera,
acquires 50 frames, and asserts no frames were dropped. Mark it with
@pytest.mark.hardware so it can be skipped in CI.
```

---

## 4. Testing NI-DAQmx and Other Modules

### 4.1 NI-DAQmx Device Discovery

Ask Claude Code to verify NI hardware is detected:

```
Run a Python script that lists all NI-DAQmx devices and their counter channels.
```

Claude Code can execute:

```python
import nidaqmx

local_system = nidaqmx.system.System.local()
for device in local_system.devices:
    print(f"Device: {device.name} ({device.product_type})")
    for co in device.co_physical_chans:
        print(f"  Counter: {co.name}")
```

### 4.2 Counter Output Test

Ask Claude Code to test TTL pulse generation:

```
Test the NIDAQmxCounter trigger: initialize it on counter channel <DEVICE/ctr0>
at 30 FPS, let it run for 5 seconds, then stop and close cleanly.
```

Claude Code should verify:
- `initialize()` returns `True`
- The NI task starts without errors
- `close()` stops the task cleanly
- No `nidaqmx.errors.DaqError` exceptions are raised

### 4.3 UDP Socket Trigger Test

The UDP socket trigger (`rataGUI/triggers/udp_socket.py`) can be tested without hardware:

```powershell
pytest tests/test_udp_socket.py -v
```

Ask Claude Code to also test round-trip communication:

```
Write a test that initializes the UDP socket trigger, sends a test signal,
and verifies the message was transmitted to the correct address and port.
```

### 4.4 Plugin Pipeline Test

Test the full plugin pipeline with mock data:

```powershell
pytest tests/test_base_plugin.py tests/test_metadata_writer.py -v
```

### 4.5 Running All Module Unit Tests

```powershell
pytest tests/ -v
```

This runs the full suite headlessly (PyQt6 is mocked in `conftest.py`), verifying:
- Camera base classes and registration
- Plugin lifecycle (init, process, close)
- Trigger lifecycle (init, execute, close)
- Ring buffer operations
- Video writer configuration
- Utility functions

---

## 5. Verifying Recorded Videos

RataGUI records video using FFmpeg via the `VideoWriter` plugin (`rataGUI/plugins/video_writer.py`). Videos are saved as `.mp4` (or `.raw` for rawvideo codec) alongside frame index and timestamp files.

### 5.1 Video Integrity Check

After a recording session, ask Claude Code to validate the output files:

```
Check the recorded video at <path\to\video_YYYY_MM_DD_HH_MM_SS\filename.mp4>.
Verify:
1. The file is not empty and can be opened
2. The total frame count matches what was expected
3. No frames are corrupted (decode every frame)
4. Frame dimensions match the camera resolution
```

Claude Code can run:

```python
import cv2
import os

video_path = r"<path_to_video>.mp4"
cap = cv2.VideoCapture(video_path)

if not cap.isOpened():
    print("ERROR: Cannot open video file")
else:
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"Resolution: {width}x{height}, FPS: {fps}, Total frames: {total_frames}")

    decoded = 0
    corrupted = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame is None or frame.size == 0:
            corrupted += 1
        decoded += 1

    cap.release()
    print(f"Decoded: {decoded}, Corrupted: {corrupted}, Missing: {total_frames - decoded}")
```

### 5.2 Frame Index Validation

The VideoWriter optionally writes a binary frame index file (`frameindex_<name>`) and a timestamps file (`timestamps_<name>.txt`). Ask Claude Code to validate them:

```
Read the frame index file and timestamps file alongside the video.
Verify that:
1. The number of frame indices matches the video frame count
2. Frame indices are sequential (no gaps)
3. Timestamps are monotonically increasing
4. The time span of timestamps matches expected recording duration
```

Claude Code can run:

```python
import numpy as np

# Read binary frame index (uint32 little-endian)
index_path = r"<path>\frameindex_<name>"
indices = np.fromfile(index_path, dtype=np.uint32)
print(f"Frame indices: {len(indices)} entries")
print(f"Range: {indices[0]} to {indices[-1]}")

# Check for gaps
diffs = np.diff(indices)
gaps = np.where(diffs != 1)[0]
if len(gaps) > 0:
    print(f"WARNING: {len(gaps)} gap(s) in frame index at positions: {gaps[:10]}")
else:
    print("Frame indices are sequential (no gaps)")

# Read timestamps
ts_path = r"<path>\timestamps_<name>.txt"
with open(ts_path) as f:
    timestamps = [float(line.strip()) for line in f if line.strip()]
print(f"Timestamps: {len(timestamps)} entries")
print(f"Duration: {timestamps[-1] - timestamps[0]:.2f} seconds")

# Check monotonicity
ts_arr = np.array(timestamps)
non_mono = np.where(np.diff(ts_arr) <= 0)[0]
if len(non_mono) > 0:
    print(f"WARNING: {len(non_mono)} non-monotonic timestamp(s)")
else:
    print("Timestamps are monotonically increasing")
```

### 5.3 FFmpeg Probe

For deeper inspection, Claude Code can use ffprobe:

```powershell
ffprobe -v error -show_format -show_streams "<path_to_video>.mp4"
```

This reports codec, duration, bitrate, pixel format, and frame count at the container level.

### 5.4 Visual Spot-Check

Ask Claude Code to extract and display sample frames:

```
Extract frames 0, 100, 500, and the last frame from the video.
Save them as PNGs so I can visually inspect them.
```

### 5.5 Automated Video Writer Tests

The existing test suite covers VideoWriter configuration extensively:

```powershell
pytest tests/test_video_writer.py -v
```

This validates codec selection, NVENC preset mapping, pixel format validation, rate control, and SVT-AV1 configuration — all without requiring a GPU or camera.

---

## 6. Testing GUI Buttons and Interaction

RataGUI uses PyQt6 for its GUI. The main window (`rataGUI/interface/main_window.py`) has three primary buttons: **Start**, **Pause**, and **Stop**.

### 6.1 Headless Unit Tests (No Display Required)

The existing test suite mocks PyQt6 in `conftest.py`, allowing all tests to run without a display:

```powershell
pytest tests/ -v
```

This works because `conftest.py` replaces PyQt6 modules with `MagicMock` objects before any rataGUI imports.

### 6.2 GUI Interaction Tests with pytest-qt

For testing actual GUI behavior (button clicks, widget state changes), install **pytest-qt**:

```powershell
python -m pip install pytest-qt
```

Then ask Claude Code to write GUI tests:

```
Write pytest-qt tests for the RataGUI MainWindow that:
1. Click the Start button and verify camera widgets are created
2. Click Pause and verify the pipeline is paused
3. Click Stop and verify cleanup happens
4. Verify button colors match the expected scheme (dark mode)
```

Example test structure Claude Code can create:

```python
import pytest
from PyQt6.QtCore import Qt

@pytest.fixture
def main_window(qtbot):
    """Create a MainWindow with no real cameras (empty lists)."""
    from rataGUI.interface.main_window import MainWindow
    window = MainWindow(camera_models=[], plugins=[], trigger_types=[])
    qtbot.addWidget(window)
    return window

def test_start_button_exists(main_window):
    assert main_window.start_button is not None
    assert main_window.start_button.isEnabled()

def test_start_button_click(main_window, qtbot):
    qtbot.mouseClick(main_window.start_button, Qt.MouseButton.LeftButton)
    # Verify expected state changes after clicking Start

def test_pause_button_click(main_window, qtbot):
    qtbot.mouseClick(main_window.pause_button, Qt.MouseButton.LeftButton)
    # Verify pipeline is paused

def test_stop_button_click(main_window, qtbot):
    qtbot.mouseClick(main_window.stop_button, Qt.MouseButton.LeftButton)
    # Verify cleanup
```

> **Note:** pytest-qt tests require a display. On Windows 11 this works natively. If running headless (e.g., in a remote session), set `QT_QPA_PLATFORM=offscreen`:
> ```powershell
> set QT_QPA_PLATFORM=offscreen
> pytest tests/test_gui.py -v
> ```

### 6.3 Manual GUI Testing via Claude Code

You can launch RataGUI and ask Claude Code to help debug interactively:

```powershell
# Launch RataGUI
python -m rataGUI.main
```

Or use the provided Windows batch file (update paths as needed):

```powershell
rataGUI.bat
```

Then describe what you observe to Claude Code:

```
I clicked Start with 2 FLIR cameras selected and the VideoWriter plugin enabled.
Camera 1 shows frames but Camera 2 shows a black screen. Help me debug this.
```

Claude Code can then:
- Read the log output for errors
- Check camera serial numbers and configuration
- Inspect the camera process for exceptions
- Suggest diagnostic scripts to isolate the issue

### 6.4 Testing Start Menu Configuration

The Start Menu (`rataGUI/interface/start_menu.py`) lets users select which camera, plugin, and trigger modules to enable. Ask Claude Code:

```
Write a test that creates the StartMenu dialog, selects FLIRCamera and VideoWriter
modules, and verifies the launch_config is updated correctly.
```

### 6.5 Widget State Verification

Ask Claude Code to write tests that verify UI state after actions:

```
Write tests that verify:
1. After Start: camera list items turn DarkMagenta (dark mode) or Green (light mode)
2. After Pause: items turn DarkGray (dark mode) or LightGray (light mode)
3. After Stop: items return to Black (dark mode) or DarkGray (light mode)
4. Camera stats update every 250ms when a camera is running
```

---

## 7. Running the Full Test Suite

### 7.1 Quick Summary

```powershell
# Activate environment
conda activate rataGUI

# Run all unit tests (no hardware needed)
pytest tests/ -v

# Run specific test modules
pytest tests/test_video_writer.py -v       # Video encoding config
pytest tests/test_base_camera.py -v        # Camera abstractions
pytest tests/test_base_trigger.py -v       # Trigger abstractions
pytest tests/test_frame_ring_buffer.py -v  # Shared memory ring buffer
pytest tests/test_camera_process.py -v     # Multiprocess acquisition

# Run with coverage report
python -m pip install pytest-cov
pytest tests/ --cov=rataGUI --cov-report=term-missing
```

### 7.2 Asking Claude Code to Run Tests

Simply tell Claude Code:

```
Run the full test suite and report any failures.
```

Or for targeted testing:

```
Run the video writer tests and explain any failures.
```

Claude Code will execute `pytest`, parse the output, and explain any failures with suggested fixes.

---

## 8. Troubleshooting

### PySpin ImportError

```
ImportError: DLL load failed while importing PySpin
```

**Fix:** Ensure the Spinnaker SDK is installed for your exact Python version (3.10) and architecture (64-bit). Restart your terminal after installation.

### NI-DAQmx Device Not Found

```
nidaqmx.errors.DaqError: Device not found
```

**Fix:** Open NI MAX (Measurement & Automation Explorer) on Windows and verify the device appears. Ensure the NI-DAQmx driver version matches your hardware.

### FFmpeg Not Found

```
IOError: Could not find ffmpeg executable in the environment PATH
```

**Fix:** If using conda, ffmpeg should be included. Verify with `ffmpeg -version`. If missing, run `conda install ffmpeg` or install from https://ffmpeg.org/download.html and add to PATH.

### Qt Platform Plugin Error

```
qt.qpa.plugin: Could not find the Qt platform plugin "windows"
```

**Fix:** Ensure PyQt6 is installed in the active conda environment: `python -m pip install pyqt6==6.4.*`. If running headless, set `QT_QPA_PLATFORM=offscreen`.

### Video File Appears Corrupted

Ask Claude Code:

```
The video file looks corrupted. Run ffprobe on it and check the ffmpeg stderr log
in the session directory for encoding errors.
```

Claude Code can check for:
- FFmpeg process exit codes
- Incomplete writes (process killed mid-recording)
- Codec/pixel format mismatches
- NVENC errors (driver version, GPU memory)

### Dropped Frames

If `FLIRCamera.frames_dropped > 0`:

```
Check the FLIR camera buffer settings. Current buffer mode and size may need tuning.
Also check if the USB3 bandwidth is saturated (multiple cameras on one controller).
```

Claude Code can help by:
- Inspecting `Buffer Mode` and `Buffer Size` in the camera config
- Checking if exposure time is too long for the target framerate
- Reviewing the camera process logs for timing issues
