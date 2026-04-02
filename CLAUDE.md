# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RataGUI is a Python GUI framework for real-time animal tracking and behavioral control. It connects video streams from cameras to online processing pipelines that can trigger external devices in real-time with low-latency closed-loop feedback. Built with PyQt6.

## Build & Development Setup

```bash
# Create conda environment (CPU)
conda create -n rataGUI ffmpeg pip scipy python=3.10

# Or GPU-enabled
conda create -n rataGUI ffmpeg pip scipy python=3.10 cudnn=8.2 cudatoolkit=11.3 nvidia::cuda-nvcc=11.3

conda activate rataGUI

# Install in editable mode with test dependencies
pip install -e ".[test]"
```

## Running Tests

```bash
pytest                                    # All tests
pytest tests/test_video_writer.py         # Single file
pytest tests/test_video_writer.py::TestConfigureNvenc  # Single class
pytest tests/test_video_writer.py::TestConfigureNvenc::test_success  # Single test
```

Tests run headlessly — PyQt6 is mocked in `tests/conftest.py` before any rataGUI imports. No display or Qt installation required. Some integration tests (e.g., `TestVideoIntegrity`) require ffmpeg on PATH and are skipped if unavailable.

## Architecture

### Module Registration Pattern

Cameras, plugins, and triggers all use the same pattern: an abstract base class with `__init_subclass__` that auto-registers subclasses into a `modules` dict. Dynamic loading in each package's `__init__.py` imports modules listed in `launch_config.json` (or all modules if showing the start menu).

- **Cameras**: Subclass `BaseCamera` (`cameras/BaseCamera.py`). Implement `getAvailableCameras()`, `initializeCamera()`, `readCamera()`, `closeCamera()`.
- **Plugins**: Subclass `BasePlugin` (`plugins/base_plugin.py`). Implement `process(frame, metadata) -> (frame, metadata)`.
- **Triggers**: Subclass `BaseTrigger` (`triggers/base_trigger.py`). Implement `getAvailableDevices()`, `initialize()`, `execute()`.

Template files are provided: `cameras/TemplateCamera.py`, `plugins/template_plugin.py`, `triggers/template_trigger.py`.

### Pipeline Data Flow

Each `CameraWidget` (`interface/camera_widget.py`) runs its own asyncio event loop:

1. **Acquisition**: `acquire_frames` reads from camera via ThreadPoolExecutor
2. **Serial plugins**: Chained via `out_queue` → next plugin's `in_queue`
3. **Independent plugins** (at end of chain): Fan-out with zero-copy via `FrameRingBuffer`
4. **Blocking plugins** (I/O-bound like VideoWriter): Run in ThreadPoolExecutor
5. **Non-blocking plugins** (like FrameDisplay): Run in asyncio event loop

Multi-process mode (`camera_process.py`) uses shared memory + queues to eliminate GIL contention for multi-camera setups.

### Plugin Properties

- `blocking`: If True, runs in thread pool (for I/O); if False, runs in event loop
- `independent`: If True, can run in parallel via fan-out with other independent plugins
- `drop_policy`: "block" (wait) or "drop_oldest" (discard oldest when queue full)

### Configuration System

Uses `pyqtconfig.ConfigManager`. Each module defines `DEFAULT_PROPS` or `DEFAULT_CONFIG` dicts that auto-generate UI widgets. Session state saved as JSON in `launch_config.json`.

### Key Source Paths

- `rataGUI/main.py` — Entry point, start menu or direct launch
- `rataGUI/interface/camera_widget.py` — Core pipeline orchestration (acquisition, fan-out, plugin scheduling)
- `rataGUI/frame_ring_buffer.py` — Zero-copy ring buffer for multi-consumer frame sharing
- `rataGUI/camera_process.py` — Multi-process camera acquisition target
- `rataGUI/interface/main_window.py` — Main Qt window
- `tests/conftest.py` — Shared fixtures and PyQt6 mocking

### Testing Patterns

- PyQt6/pyqtconfig mocked at import time in conftest.py for headless testing
- Hardware (cameras, GPU/NVENC, NI-DAQ, sockets) mocked via `unittest.mock`
- `mock_cam_widget`, `mock_config_manager`, `sample_frame`, `sample_metadata` are shared fixtures
- Video writer tests reset module-level caches (`_nvidia_driver_version_cache`, etc.) in `setup_method`
- Async tests use `asyncio_mode = "auto"` (pytest-asyncio)

## Git Workflow

Fork-based workflow. Origin: `jdk20/rataGUI`, upstream: `BrainHu42/rataGUI`. Main branch: `main`.
