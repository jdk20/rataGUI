# RataGUI

[![Downloads](https://static.pepy.tech/badge/ratagui)](https://pepy.tech/project/ratagui) 
[![Downloads](https://static.pepy.tech/badge/ratagui/month)](https://pepy.tech/project/ratagui)
[![PyPI version](https://badge.fury.io/py/rataGUI.svg)](https://badge.fury.io/py/rataGUI)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Generic badge](https://img.shields.io/badge/Contributions-Welcome-brightgreen.svg)](CONTRIBUTING.md)

<div align="center">
<p align="center">
<img src="docs/images/banner.png" width="95%">
</p>
</div>

RataGUI is a **customizable** and **user-friendly** Python framework for real-time animal tracking and behavioral control. At a high level, it connects video streams from cameras to online processing pipelines that can trigger external devices in real-time, enabling experiments with low latency, closed-loop feedback. 


# Features
RataGUI was developed with four primary design principles:

* **Accessibility** - RataGUI features an adaptive and intuitive graphical user interface (GUI) that makes it easier to conduct complex experiments involving heterogenous hardware without any additional programming. Using minimal dependencies and efficient multi-threaded and multi-process processing, RataGUI is designed to run on a wide variety of different systems.

* **Modularity** - RataGUI's plug-and-play architecture enables easy customization of data processing pipelines to support your experiment's specific needs. Cameras, plugins and triggers are separated into individual modules (see tables below) and configured together in a single unified interface.

* **Extensibility** - RataGUI's modular framework allows for seamless integration of user-created modules for additional functionality. You are encouraged to fork the repository and write additional modules using the provided instructions and template code. RataGUI aims to provide a platform for researchers to share code and contribute to the growing list of modules below.

* **Reproducibility** - RataGUI automatically logs all relevant experimental info and saves its state in a restorable, human-readable JSON format. This allows RataGUI to replicate an experiment's parameters from a single session directory. 

## Available Camera Modules
| Name | Description | Contributor |
| -------- | -------- | -------- |
| BaslerCamera | Basler camera integration using pypylon (see installation guide) | [BrainHu42](https://github.com/BrainHu42) |
| FLIRCamera  | Spinnaker camera integration using PySpin (see installation guide) | [BrainHu42](https://github.com/BrainHu42) <br>[nathanielnyema](https://github.com/nathanielnyema) |
| VideoReader | Reads video files for offline processing  | [BrainHu42](https://github.com/BrainHu42) |
| WebCamera | OpenCV integration for web cameras or network cameras | [BrainHu42](https://github.com/BrainHu42) |


## Available Plugin Modules
| Name | Description | Contributor |
| -------- | -------- | -------- |
| DLCInference | Estimates animal poses using exported DeepLabCut model and writes keypoints as metadata | [BrainHu42](https://github.com/BrainHu42) <br>[nathanielnyema](https://github.com/nathanielnyema) |
| FrameDisplay  | Displays video stream in a separate window | [BrainHu42](https://github.com/BrainHu42) |
| MetadataWriter | Overlays metadata onto frames and/or into a log file | [BrainHu42](https://github.com/BrainHu42) |
| SleapInference | Estimates animal poses using exported SLEAP model and writes keypoints as metadata | [BrainHu42](https://github.com/BrainHu42) |
| VideoWriter | Writes frames to video file using FFMPEG (supports NVENC hardware acceleration) | [BrainHu42](https://github.com/BrainHu42) |
| Pixel2World | Converts pixel space to real world coordinates using MATLAB camera calibration file | [nathanielnyema](https://github.com/nathanielnyema) |
| Undistort | Undistorts video stream given camera parameters in MATLAB camera calibration file | [nathanielnyema](https://github.com/nathanielnyema) |

## Available Trigger Modules
| Name | Description | Contributor |
| -------- | -------- | -------- |
| NIDAQmxCounter | Writes tasks to National Instrument counter cards through the NI-DAQmx driver | [BrainHu42](https://github.com/BrainHu42) |
| UDPSocket  | Publishes information to a network socket using UDP protocol | [BrainHu42](https://github.com/BrainHu42) |


# [Installation Guide](docs/install-guide.md)

## Quick Start
```
conda create -n rataGUI ffmpeg pip scipy python=3.10 cudnn=8.2 cudatoolkit=11.3 nvidia::cuda-nvcc=11.3
conda activate rataGUI
python -m pip install rataGUI
```
<!-- # Documentation

Note: A "session" is a recording session. Every time you press start, it starts a new recording session and saves a snapshot of RataGUI's state.

## Video Demo -->


# Development Guide

RataGUI's modular framework was built for user customizability and integration. We encourage you to [fork](https://guides.github.com/activities/forking/#fork) the package [Github repository](https://github.com/BrainHu42/rataGUI) and add additional modules for your specific use case. Then, clone the forked repository and install in editable mode:
```
git clone https://github.com/<YOUR-USERNAME>/rataGUI.git
cd rataGUI
conda create -n rataGUI ffmpeg pip python=3.10
conda activate rataGUI
python -m pip install -e ".[test]"
```

This installs rataGUI in editable mode so that any source changes take effect immediately without reinstalling.

## Implement Custom Camera Models
To add another camera model, simply rename and edit the required functions provided in `cameras/TemplateCamera.py` to fit your camera model's specifications. RataGUI will use these functions to find, initialize, read frames from and close the camera. Any configurable camera settings should be specified in the dictionary named `DEFAULT_PROPS`. RataGUI will use these default settings to automatically create a dynamic menu and add it to the user interface. The configured settings will be passed into the `initializeCamera` function.

## Implement Custom Plugins
To incorporate additional functionality, simply rename and edit the required functions provided in `plugins/template_plugin.py` with the custom processing needed for your use case. RataGUI will use these functions to attach your plugin to an active camera widget's processing pipeline. Any configurable plugin settings should be specified in the dictionary named `DEFAULT_CONFIG`. RataGUI will use these default settings to automatically create a dynamic menu and add it to the user interface. 

## Implement Custom Triggers
To interface with other external devices, simply rename and edit the required functions provided in `triggers/template_trigger.py` to fit your custom use case. RataGUI will use these functions to populate the trigger tab in the user interface with all available devices and their configurable settings. Trigger devices can be controlled through the interface as well as within a plugin process. 

## Running Tests
RataGUI includes a comprehensive test suite. If you used the development install above, pytest is already included. To run the tests:
```
pytest
```

## Contributing
If you think your module would be useful to other people, please consider submitting a merge request so that we can review and integrate your code into the main branch. We'll also add you to the list of module contributors!
