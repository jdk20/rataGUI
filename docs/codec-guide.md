# Video Codec Guide

RataGUI records video through the **VideoWriter** plugin, which uses FFmpeg under the hood. You can choose from several CPU-based and GPU-accelerated codecs depending on your hardware, performance needs, and file-size constraints.

## CPU Codecs

### libx264 (H.264 / AVC)

The most widely supported video codec. A safe default for maximum compatibility.

| | |
|---|---|
| **Pros** | Universal playback support across all devices and players. Wide range of speed presets (`ultrafast` to `veryslow`). Mature, well-optimized encoder. Low CPU usage at faster presets. |
| **Cons** | Less compression-efficient than H.265 or AV1 — larger files at the same quality. Older standard with no further development. |

- **Presets:** ultrafast, veryfast, faster, fast, medium, slow, slower, veryslow
- **Quality:** CRF 0–51 (lower = better quality, default 32)

### libx265 (H.265 / HEVC)

Next-generation codec offering ~50% better compression than H.264 at equivalent quality.

| | |
|---|---|
| **Pros** | Significantly smaller files than H.264 at the same visual quality. Same preset range as libx264. Good for archival or storage-constrained setups. |
| **Cons** | Slower encoding than libx264, especially at slower presets. Playback compatibility is narrower — some older players and browsers lack H.265 support. Licensing considerations in some commercial contexts. |

- **Presets:** ultrafast, veryfast, faster, fast, medium, slow, slower, veryslow
- **Quality:** CRF 0–51 (lower = better quality, default 32)

### libsvtav1 (AV1)

A royalty-free, open-standard codec with state-of-the-art compression efficiency.

| | |
|---|---|
| **Pros** | Best compression efficiency of all CPU codecs — smallest files at a given quality. Completely royalty-free and open source. Growing playback support in modern browsers and players. |
| **Cons** | Slowest CPU encoding of the three. Requires a recent FFmpeg build with SVT-AV1 compiled in. Limited playback on older devices and software. |

- **Presets:** 0 (slowest/best) to 13 (fastest), or text names mapped automatically (ultrafast → 12, medium → 5, veryslow → 0)
- **Quality:** CRF 0–51 (lower = better quality, default 32)

## GPU Codecs (NVIDIA NVENC)

GPU codecs offload encoding to dedicated hardware on NVIDIA GPUs, freeing the CPU for other tasks like ML inference. All NVENC codecs require an NVIDIA GPU with NVENC support.

### h264_nvenc (NVIDIA H.264)

Hardware-accelerated H.264 encoding via NVENC.

| | |
|---|---|
| **Pros** | Extremely fast encoding with near-zero CPU usage. Low-latency tuning modes (`ll`, `ull`) ideal for real-time applications. Broad output compatibility (H.264). |
| **Cons** | Requires an NVIDIA GPU. Slightly lower quality-per-bitrate compared to software libx264 at slow presets. Limited to NVENC session caps on consumer GPUs. |

- **Presets:** p1 (fastest) to p7 (best quality) on SDK 10+ drivers (≥456); legacy drivers use fast/medium/slow
- **Quality:** CQ 0–51 (constant quality via `-cq`, default 32)
- **Rate control:** auto (constqp), constqp, vbr, cbr
- **Tune:** none, hq (high quality), ll (low latency), ull (ultra-low latency)
- **B-Frames:** 0–4

### hevc_nvenc (NVIDIA H.265 / HEVC)

Hardware-accelerated H.265 encoding via NVENC.

| | |
|---|---|
| **Pros** | Fast GPU encoding with better compression than h264_nvenc. B-frame support for improved compression. Same low-latency tuning options. |
| **Cons** | Requires an NVIDIA GPU. Quality gap vs. software libx265 at very slow presets. Narrower playback support than H.264. |

- **Presets:** Same as h264_nvenc (p1–p7 or legacy)
- **Quality:** CQ 0–51
- **Rate control:** auto, constqp, vbr, cbr
- **Tune:** none, hq, ll, ull
- **B-Frames:** 0–4

### av1_nvenc (NVIDIA AV1)

Hardware-accelerated AV1 encoding, available on Ada Lovelace (RTX 40-series) and newer GPUs.

| | |
|---|---|
| **Pros** | Fast AV1 encoding on GPU. Royalty-free output format. Excellent compression efficiency. |
| **Cons** | Requires NVIDIA driver ≥520 (NVENC SDK 12+) and an Ada Lovelace or newer GPU. Does **not** support B-frames. Limited to the newest hardware generation. |

- **Presets:** Same as h264_nvenc (p1–p7 or legacy)
- **Quality:** CQ 0–51
- **Rate control:** auto, constqp, vbr, cbr
- **B-Frames:** Not supported (setting is ignored)

## Raw Video

### rawvideo (Uncompressed)

Writes raw, uncompressed pixel data. Output uses the `.raw` extension.

| | |
|---|---|
| **Pros** | Zero quality loss — pixel-perfect recording. No encoding latency. |
| **Cons** | Enormous file sizes (e.g., 1080p RGB at 30 fps ≈ 5.6 GB/min). Not directly playable in most video players without conversion. |

## Comparison Table

| Codec | Type | Speed | Compression | Compatibility | GPU Required | Best For |
|---|---|---|---|---|---|---|
| libx264 | CPU | Fast | Good | Excellent | No | General use, maximum compatibility |
| libx265 | CPU | Moderate | Very good | Good | No | Storage-constrained archival |
| libsvtav1 | CPU | Slow | Excellent | Growing | No | Best compression, royalty-free output |
| h264_nvenc | GPU | Very fast | Good | Excellent | Yes (NVIDIA) | Real-time recording, low latency |
| hevc_nvenc | GPU | Very fast | Very good | Good | Yes (NVIDIA) | GPU recording with better compression |
| av1_nvenc | GPU | Very fast | Excellent | Growing | Yes (NVIDIA, RTX 40+) | Newest GPUs, royalty-free |
| rawvideo | CPU | Instant | None | Low | No | Debugging, lossless archival |

## Configuration Tips

- **Preset** controls the speed/quality tradeoff. Faster presets encode quicker but produce larger files. For real-time recording, start with a fast preset and only slow down if you have CPU/GPU headroom.
- **CRF / CQ** (quality) ranges from 0 (lossless) to 51 (worst). Values around 18–28 are typical for good visual quality. The default of 32 prioritizes smaller files.
- **Rate control** (NVENC only): `constqp` is the default and works like CRF. Use `vbr` or `cbr` when you need predictable bitrates.
- **Pixel format**: `yuv420p` is the most compatible. Use `yuv444p` or 10-bit formats only when you need full chroma or higher bit depth.
- **GPU Pixel Conversion**: When enabled, pixel format conversion happens on the GPU via CUDA, reducing CPU load for high-resolution streams. Requires FFmpeg compiled with CUDA support.
