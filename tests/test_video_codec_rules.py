"""Tests for rataGUI.plugins.video_codec_rules."""

import pytest

from rataGUI.plugins.video_codec_rules import (
    NVENC_CODECS,
    NVENC_ONLY_KEYS,
    B_FRAMES_CODECS,
    PRESETS_BY_CODEC,
    PIXEL_FORMATS_BY_CODEC,
    get_hidden_keys,
    get_valid_presets,
    get_valid_pixel_formats,
    validate_config,
)


# ---------------------------------------------------------------------------
# get_hidden_keys
# ---------------------------------------------------------------------------


class TestGetHiddenKeys:
    def test_libx264_hides_nvenc_and_bframes(self):
        hidden = get_hidden_keys("libx264")
        for key in NVENC_ONLY_KEYS:
            assert key in hidden
        assert "B-Frames" in hidden

    def test_libx265_hides_nvenc_and_bframes(self):
        hidden = get_hidden_keys("libx265")
        for key in NVENC_ONLY_KEYS:
            assert key in hidden
        assert "B-Frames" in hidden

    def test_libsvtav1_hides_nvenc_and_bframes(self):
        hidden = get_hidden_keys("libsvtav1")
        for key in NVENC_ONLY_KEYS:
            assert key in hidden
        assert "B-Frames" in hidden

    def test_h264_nvenc_shows_nvenc_keys_and_bframes(self):
        hidden = get_hidden_keys("h264_nvenc")
        for key in NVENC_ONLY_KEYS:
            assert key not in hidden
        assert "B-Frames" not in hidden

    def test_hevc_nvenc_shows_nvenc_keys_and_bframes(self):
        hidden = get_hidden_keys("hevc_nvenc")
        for key in NVENC_ONLY_KEYS:
            assert key not in hidden
        assert "B-Frames" not in hidden

    def test_av1_nvenc_shows_nvenc_keys_but_hides_bframes(self):
        hidden = get_hidden_keys("av1_nvenc")
        for key in NVENC_ONLY_KEYS:
            assert key not in hidden
        assert "B-Frames" in hidden

    def test_rawvideo_hides_all_codec_specific_options(self):
        hidden = get_hidden_keys("rawvideo")
        assert "speed (preset)" in hidden
        assert "quality (0-51)" in hidden
        assert "pixel format" in hidden
        for key in NVENC_ONLY_KEYS:
            assert key in hidden
        assert "B-Frames" in hidden

    def test_universal_keys_never_hidden(self):
        """framerate, buffer size, save dir, etc. should never be hidden."""
        universal = {"framerate", "Write Frame Index", "Buffer Size (frames)",
                     "Save directory", "filename suffix"}
        for codec in PRESETS_BY_CODEC:
            hidden = get_hidden_keys(codec)
            assert hidden.isdisjoint(universal), f"{codec} hides universal keys"


# ---------------------------------------------------------------------------
# get_valid_presets
# ---------------------------------------------------------------------------


class TestGetValidPresets:
    def test_libx264_presets(self):
        presets = get_valid_presets("libx264")
        assert "medium" in presets
        assert "ultrafast" in presets
        assert "veryslow" in presets
        assert "p4" not in presets

    def test_nvenc_presets_include_both_families(self):
        for codec in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
            presets = get_valid_presets(codec)
            assert "p1" in presets
            assert "p7" in presets
            assert "fast" in presets
            assert "ultrafast" not in presets

    def test_rawvideo_empty_presets(self):
        assert get_valid_presets("rawvideo") == []

    def test_libsvtav1_includes_numeric_and_text(self):
        presets = get_valid_presets("libsvtav1")
        assert "0" in presets
        assert "13" in presets
        assert "medium" in presets
        assert "p4" not in presets


# ---------------------------------------------------------------------------
# get_valid_pixel_formats
# ---------------------------------------------------------------------------


class TestGetValidPixelFormats:
    def test_nvenc_restricted_set(self):
        for codec in NVENC_CODECS:
            fmts = get_valid_pixel_formats(codec)
            assert "yuv420p" in fmts
            assert "nv12" in fmts
            assert "yuv422p" not in fmts
            assert "rgb24" not in fmts

    def test_cpu_full_set(self):
        for codec in ("libx264", "libx265", "libsvtav1"):
            fmts = get_valid_pixel_formats(codec)
            assert "yuv420p" in fmts
            assert "yuv422p" in fmts
            assert "rgb24" in fmts

    def test_rawvideo_empty(self):
        assert get_valid_pixel_formats("rawvideo") == []

    def test_unknown_codec_returns_full_set(self):
        fmts = get_valid_pixel_formats("unknown_codec")
        assert "yuv420p" in fmts
        assert "rgb24" in fmts


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------


class TestValidateConfig:
    def test_valid_libx264_config(self):
        errors = validate_config("libx264", {
            "speed (preset)": "medium",
            "pixel format": "yuv420p",
        })
        assert errors == []

    def test_valid_nvenc_config(self):
        errors = validate_config("h264_nvenc", {
            "speed (preset)": "p4",
            "pixel format": "yuv420p",
            "Rate Control": "constqp",
            "B-Frames": 2,
        })
        assert errors == []

    def test_rate_control_invalid_for_libx264(self):
        errors = validate_config("libx264", {"Rate Control": "cbr"})
        assert len(errors) == 1
        assert "Rate Control" in errors[0]
        assert "libx264" in errors[0]

    def test_nvenc_only_keys_invalid_for_cpu_codecs(self):
        for key in NVENC_ONLY_KEYS:
            errors = validate_config("libx265", {key: "some_value"})
            assert len(errors) >= 1, f"Expected error for {key} with libx265"

    def test_invalid_preset_for_libx264(self):
        errors = validate_config("libx264", {"speed (preset)": "p4"})
        assert len(errors) == 1
        assert "p4" in errors[0]

    def test_invalid_preset_for_nvenc(self):
        errors = validate_config("h264_nvenc", {"speed (preset)": "ultrafast"})
        assert len(errors) == 1
        assert "ultrafast" in errors[0]

    def test_invalid_pixfmt_for_nvenc(self):
        errors = validate_config("h264_nvenc", {"pixel format": "rgb24"})
        assert len(errors) == 1
        assert "rgb24" in errors[0]

    def test_bframes_invalid_for_av1_nvenc(self):
        errors = validate_config("av1_nvenc", {"B-Frames": 2})
        assert len(errors) == 1
        assert "B-Frames" in errors[0]

    def test_bframes_valid_for_h264_nvenc(self):
        errors = validate_config("h264_nvenc", {"B-Frames": 2})
        assert errors == []

    def test_rawvideo_with_preset_errors(self):
        errors = validate_config("rawvideo", {"speed (preset)": "fast"})
        assert len(errors) >= 1

    def test_strict_mode_raises_valueerror(self):
        with pytest.raises(ValueError, match="Rate Control"):
            validate_config("libx264", {"Rate Control": "cbr"}, strict=True)

    def test_strict_raises_on_first_error(self):
        with pytest.raises(ValueError):
            validate_config("libx264", {
                "Rate Control": "cbr",
                "speed (preset)": "p4",
            }, strict=True)

    def test_non_strict_returns_all_errors(self):
        errors = validate_config("libx264", {
            "Rate Control": "cbr",
            "speed (preset)": "p4",
        })
        assert len(errors) == 2

    def test_only_user_provided_keys_checked(self):
        """Keys not in user_config should not trigger errors."""
        errors = validate_config("libx264", {"speed (preset)": "medium"})
        assert errors == []

    def test_empty_user_config_no_errors(self):
        errors = validate_config("libx264", {})
        assert errors == []
