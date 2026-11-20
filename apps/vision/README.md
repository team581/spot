# Spot vision service

The service that runs on the Jetson: capture, tag detection, pose estimation, NetworkTables, and the HTTP API.
See [Work on Spot](https://spot.frc581.com/how-to/develop/).

## Detector corpus

`spot-vision corpus` takes a JSON list of `{file, scenario, tags: [{id, corners, partial?}]}` with 8-bit PGM images next to it. List the four black-square corners in either winding, with the first pixel centered at `(0, 0)`.

A detection must have the right ID and a quad intersection over union of at least 0.5. Each label takes its best remaining match, and complete tags take priority over partial tags. Matches to `partial: true` labels are ignored. Any remaining detection is unmatched, not necessarily a wrong ID. The `≤1 px` column counts complete tags with all four corners at most one pixel off after alignment, divided by **all** complete labels, including misses.

### Baseline: Nov. 20, 2026

Detector revision `ba494dc`, release build on Apple M4 Pro, default detector settings (`min_tag_px=32`, no lens calibration). Latency is p50/p95 across per-frame medians of five warm detection calls. It excludes file I/O, image decoding, and scoring. These are CPU measurements, not Jetson or camera-to-pose timings.

| Dataset | Frames | Found / complete | Recall | ≤1 px | p50 / p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| ICRA forward, pure tags | 50 | 3,879 / 7,700 | 50.38% | 50.38% | 3.977 / 5.435 |
| ICRA forward, checkerboard | 50 | 16 / 7,700 | 0.21% | 0.21% | 3.167 / 4.318 |
| **ICRA forward total** | **100** | **3,895 / 15,400** | **25.29%** | **25.29%** | **3.200 / 5.200** |
| Locus single tag, 640 × 480 | 50 | 46 / 50 | 92.00% | 90.00% | 0.232 / 0.383 |
| Locus single tag, 1280 × 720 | 50 | 48 / 50 | 96.00% | 94.00% | 0.714 / 1.214 |
| Locus single tag, 1920 × 1080 | 50 | 47 / 50 | 94.00% | 92.00% | 1.672 / 2.863 |
| Locus single tag, 3840 × 2160 | 50 | 50 / 50 | 100.00% | 98.00% | 6.624 / 12.518 |
| Locus high ISO | 50 | 47 / 50 | 94.00% | 92.00% | 1.648 / 2.914 |
| Locus low key | 50 | 47 / 50 | 94.00% | 94.00% | 1.355 / 2.494 |
| Locus raw pipeline | 50 | 47 / 50 | 94.00% | 94.00% | 1.707 / 2.896 |
| Locus AprilGrid, golden | 150 | 2,230 / 5,157 | 43.24% | 43.24% | 2.092 / 3.338 |
| Locus AprilGrid, Brown–Conrady | 50 | 513 / 1,740 | 29.48% | 28.05% | 2.147 / 3.017 |
| Locus AprilGrid, Kannala–Brandt | 50 | 221 / 1,496 | 14.77% | 3.74% | 1.529 / 2.115 |
| **Locus tag36h11 total** | **600** | **3,296 / 8,743** | **37.70%** | **35.47%** | **1.734 / 6.219** |

No detections were unmatched or ignored. On ICRA pure-tag frames, Spot found all 1,232 tags with a shortest edge of at least 32 px and none of the 2,772 tags below 12 px. On the corresponding checkerboard frames, it found only 16 of those 1,232 larger tags.

### Reproduce the benchmark

From the repository root, use `uv` and allow about 5 GB for the downloads and converted frames. The [ICRA mirror](https://huggingface.co/datasets/NoeFontana/apriltag-validation-data) provides both forward sets. [Locus-Tag Bench](https://huggingface.co/datasets/NoeFontana/locus-tag-bench) is scored on all 10 tag36h11 campaigns, excluding tag16h5 and ChArUco.

```sh
work=$(mktemp -d)
uvx --from huggingface_hub hf download NoeFontana/apriltag-validation-data forward.tar.xz \
  --repo-type dataset --revision 6c7653385d480351fe8235d010dedc18fbc0b992 --local-dir "$work"
tar -xf "$work/forward.tar.xz" -C "$work"
uvx --from huggingface_hub hf download NoeFontana/locus-tag-bench \
  --repo-type dataset --revision 5346835a9ed350828472a4c83d6e3999cf94fefb --local-dir "$work/locus" \
  --include 'locus_v1_*/*.parquet' --include 'locus_v1_*/*truth.json' --include 'locus_v1_*/*checksums.json' \
  --include 'aprilgrid_*/*.parquet' --include 'aprilgrid_*/*truth.json' --include 'aprilgrid_*/*checksums.json' \
  --exclude 'locus_v1_tag16h5*/*'

uv run --script tools/prepare-apriltag-corpus.py icra "$work/forward" "$work/icra-pgm"
uv run --script tools/prepare-apriltag-corpus.py locus "$work/locus" "$work/locus-pgm"
cargo build --manifest-path apps/vision/Cargo.toml --release --locked --bin spot-vision
apps/vision/target/release/spot-vision corpus "$work/icra-pgm/truth.json"
apps/vision/target/release/spot-vision corpus "$work/locus-pgm/truth.json"
```

On Jetson, use the `spot-vision` binary from `nix build .#packages.aarch64-linux.spot-vision` and run the same `corpus` commands. You don't need to deploy or restart `spot-vision.service`.
