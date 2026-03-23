# Installation
RataGUI is written entirely in Python and runs on all platforms with minimal dependencies.

## Conda Installation (Recommended)

### CPU-only environment
```
conda create -n rataGUI ffmpeg pip python=3.10
conda activate rataGUI
python -m pip install rataGUI
```

### GPU-enabled environment

For real-time model inference, using a GPU is strongly encouraged to minimize latency. If you have a NVIDIA GPU, make sure the latest [driver](https://www.nvidia.com/download/index.aspx) version is installed. 
> Note: CUDA is automatically installed in the conda environment.

```
conda create -n rataGUI ffmpeg pip python=3.10 cudnn=8.2 cudatoolkit=11.3 nvidia::cuda-nvcc=11.3
conda activate rataGUI
python -m pip install rataGUI
```

## Pip Installation (CPU-only)

If you don't want to download Anaconda or its lightweight variants (miniconda, miniforge etc.), you can install RataGUI as a standalone pip package in any python>=3.10 environment. However, creating a separate virtual environment is strongly suggested so that RataGUI doesn't conflict with other installed packages. 
> Note: Unlike conda, pip can't automatically install ffmpeg for video encoding so it needs to be installed through the official download [links](https://ffmpeg.org/download.html) or using a package manager (e.g. `sudo apt install ffmpeg` on Debian/Ubuntu, `brew install ffmpeg` on macOS, etc.).

```
python -m pip install rataGUI
```

## External Hardware

### Spinnaker (FLIR) Cameras
To use RataGUI with Spinnaker (FLIR) cameras, follow the instructions [here](https://www.flir.com/products/spinnaker-sdk/) to download the full Spinnaker SDK for your specific Python version. 
In the downloaded folder, find the package wheel file (`spinnaker_python-\<version\>-\<system-info\>.whl`) and run the following command install PySpin into your Python enviornment. Then, restart the environment or reboot your computer to recapture the system and user environment variables.
```
python -m pip install <PATH-TO-SPINNAKER-WHEEL-FILE>.whl
```

### Basler (Pylon) Cameras
To use RataGUI with Basler cameras, install the python wrapper package for the PyPylon SDK. 
```
python -m pip install pypylon
```

### National Instruments (NI-DAQmx) Devices
To use RataGUI with National Instruments hardware, install the python wrapper package for the NI-DAQmx driver.
```
python -m pip install nidaqmx
```

## Running Tests
RataGUI includes a unit test suite that can be run without any hardware connected. Install the test dependencies and run:
```
pip install pytest
pytest
```