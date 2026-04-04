"""Codec-to-option compatibility rules for VideoWriter.

Single source of truth consumed by the GUI (dynamic show/hide) and the
headless runner (strict validation).  No Qt imports — pure Python data
and helpers.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Codec groupings
# ---------------------------------------------------------------------------

NVENC_CODECS = frozenset({"h264_nvenc", "hevc_nvenc", "av1_nvenc"})

#: NVENC codecs that support B-frames (av1_nvenc does not).
B_FRAMES_CODECS = frozenset({"h264_nvenc", "hevc_nvenc"})

# ---------------------------------------------------------------------------
# Config keys that only apply to certain codecs
# ---------------------------------------------------------------------------

#: Keys that only make sense for NVENC codecs.
NVENC_ONLY_KEYS = frozenset(
    {
        "Rate Control",
        "Bitrate (Mbps)",
        "GPU Index",
        "Tune",
        "GPU Pixel Conversion",
    }
)

#: Keys hidden when rawvideo is selected (essentially everything except
#: framerate, buffer size, save directory, filename suffix, frame index).
_RAWVIDEO_HIDDEN_KEYS = frozenset(
    {
        "speed (preset)",
        "quality (0-51)",
        "pixel format",
        "Rate Control",
        "Bitrate (Mbps)",
        "GPU Index",
        "B-Frames",
        "Tune",
        "GPU Pixel Conversion",
    }
)

# ---------------------------------------------------------------------------
# Valid presets per codec
# ---------------------------------------------------------------------------

_X264_PRESETS = [
    "ultrafast",
    "veryfast",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
]

# Both P-series (SDK 10+) and legacy names are offered — the driver-dependent
# mapping in _configure_nvenc() selects the right family at runtime.
_NVENC_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "fast", "medium", "slow"]

_SVTAV1_PRESETS = [
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "11",
    "12",
    "13",
    "ultrafast",
    "veryfast",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
]

PRESETS_BY_CODEC: dict[str, list[str]] = {
    "libx264": _X264_PRESETS,
    "libx265": _X264_PRESETS,
    "h264_nvenc": _NVENC_PRESETS,
    "hevc_nvenc": _NVENC_PRESETS,
    "av1_nvenc": _NVENC_PRESETS,
    "libsvtav1": _SVTAV1_PRESETS,
    "rawvideo": [],
}

# ---------------------------------------------------------------------------
# Valid pixel formats per codec
# ---------------------------------------------------------------------------

ALL_PIXEL_FORMATS = [
    "yuv420p",
    "yuv422p",
    "yuv444p",
    "rgb24",
    "yuv420p10le",
    "yuv422p10le",
    "yuv444p10le",
    "gray",
]

NVENC_PIXEL_FORMATS = ["yuv420p", "nv12", "p010le", "yuv444p", "yuv444p16le"]

PIXEL_FORMATS_BY_CODEC: dict[str, list[str]] = {
    "libx264": ALL_PIXEL_FORMATS,
    "libx265": ALL_PIXEL_FORMATS,
    "h264_nvenc": NVENC_PIXEL_FORMATS,
    "hevc_nvenc": NVENC_PIXEL_FORMATS,
    "av1_nvenc": NVENC_PIXEL_FORMATS,
    "libsvtav1": ALL_PIXEL_FORMATS,
    "rawvideo": [],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_hidden_keys(codec: str) -> frozenset[str]:
    """Return config keys that should be hidden/disabled for *codec*."""
    if codec == "rawvideo":
        return _RAWVIDEO_HIDDEN_KEYS

    hidden: set[str] = set()
    if codec not in NVENC_CODECS:
        hidden.update(NVENC_ONLY_KEYS)
    if codec not in B_FRAMES_CODECS:
        hidden.add("B-Frames")
    return frozenset(hidden)


def get_valid_presets(codec: str) -> list[str]:
    """Return the list of valid preset values for *codec*."""
    return PRESETS_BY_CODEC.get(codec, [])


def get_valid_pixel_formats(codec: str) -> list[str]:
    """Return the list of valid pixel formats for *codec*."""
    return PIXEL_FORMATS_BY_CODEC.get(codec, ALL_PIXEL_FORMATS)


# ---------------------------------------------------------------------------
# Validation (headless / API)
# ---------------------------------------------------------------------------

# Keys whose values are dropdown selections (presets / pixel formats) that
# need per-codec validation.
_PRESET_KEY = "speed (preset)"
_PIXEL_FORMAT_KEY = "pixel format"


def validate_config(
    codec: str,
    user_config: dict,
    *,
    strict: bool = False,
) -> list[str]:
    """Validate *user_config* keys against codec compatibility rules.

    Only keys present in *user_config* are checked — auto-populated
    defaults are not flagged.

    :param codec: The selected video codec name.
    :param user_config: Config dict containing only user-provided overrides.
    :param strict: If True, raise ``ValueError`` on the first error.
    :return: List of human-readable error strings (empty if valid).
    """
    errors: list[str] = []
    hidden = get_hidden_keys(codec)

    # Check inapplicable keys
    for key in hidden:
        if key in user_config:
            errors.append(f"'{key}' is not supported for codec '{codec}'")
            if strict:
                raise ValueError(errors[0])

    # Validate preset
    if _PRESET_KEY in user_config:
        preset = user_config[_PRESET_KEY]
        valid = get_valid_presets(codec)
        if valid and preset not in valid:
            msg = (
                f"Preset '{preset}' is not valid for codec '{codec}'. "
                f"Valid presets: {', '.join(valid)}"
            )
            errors.append(msg)
            if strict:
                raise ValueError(msg)
        elif not valid and preset is not None:
            msg = f"Codec '{codec}' does not support presets"
            errors.append(msg)
            if strict:
                raise ValueError(msg)

    # Validate pixel format
    if _PIXEL_FORMAT_KEY in user_config:
        pf = user_config[_PIXEL_FORMAT_KEY]
        valid_pf = get_valid_pixel_formats(codec)
        if valid_pf and pf not in valid_pf:
            msg = (
                f"Pixel format '{pf}' is not supported by codec '{codec}'. "
                f"Valid formats: {', '.join(valid_pf)}"
            )
            errors.append(msg)
            if strict:
                raise ValueError(msg)
        elif not valid_pf and pf is not None:
            msg = f"Codec '{codec}' does not support pixel format selection"
            errors.append(msg)
            if strict:
                raise ValueError(msg)

    return errors
