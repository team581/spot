# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.5.4", "opencv-python-headless==5.1.0.95", "pyarrow==26.0.1"]
# ///

"""Convert the pinned ICRA forward and Locus tag36h11 datasets to Spot corpus manifests."""

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

LOCUS_CAMPAIGNS = {
    **{
        f"locus_v1_tag36h11_{size}": 50
        for size in ("640x480", "1280x720", "1920x1080", "3840x2160")
    },
    **{
        f"locus_v1_{kind}_1920x1080": 50
        for kind in ("high_iso", "low_key", "raw_pipeline")
    },
    "aprilgrid_golden_v1_1920x1080": 150,
    "aprilgrid_distortion_brown_conrady_v1_1920x1080": 50,
    "aprilgrid_distortion_kannala_brandt_v1_1920x1080": 50,
}


def label(tag_id, corners, partial):
    if len(corners) != 4 or any(
        xy is None or len(xy) != 2 or not all(map(math.isfinite, xy)) for xy in corners
    ):
        raise ValueError(f"Invalid ground-truth corners for tag {tag_id}")
    # Both datasets use the image boundary, not the first pixel centre, as the origin.
    return {
        "id": tag_id,
        "corners": [[x - 0.5, y - 0.5] for x, y in corners],
        "partial": partial,
    }


def icra_frames(root):
    labels = defaultdict(dict)
    with (root / "tags.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            tag_id, corner = int(row["tag_id"]), int(row["corner"])
            partial = row["tag_fully_visible"] == "0"
            corners, was_partial = labels[row["image"]].setdefault(
                tag_id, ([None] * 4, partial)
            )
            if (
                not 0 <= corner < 4
                or corners[corner] is not None
                or partial != was_partial
            ):
                raise ValueError(f"Inconsistent ICRA label: {row}")
            corners[corner] = float(row["ground_truth_x"]), float(row["ground_truth_y"])

    for variant in ("pure_tags_images", "checkerboard_corners_images"):
        images = sorted((root / variant).glob("*.png"))
        if len(images) != 50 or {p.name for p in images} != labels.keys():
            raise ValueError(f"Incomplete ICRA forward variant: {variant}")
        for path in images:
            tags = [label(tag_id, *data) for tag_id, data in labels[path.name].items()]
            yield f"icra-forward/{variant}", path.stem, path.read_bytes(), tags


def locus_frames(root):
    for campaign, expected in LOCUS_CAMPAIGNS.items():
        source = root / campaign
        checksums = json.loads((source / "checksums.json").read_bytes())["files"]
        truth = (source / "rich_truth.json").read_bytes()
        if hashlib.sha256(truth).hexdigest() != checksums["rich_truth.json"]:
            raise ValueError(f"Locus label checksum mismatch: {campaign}")
        labels = defaultdict(list)
        for tag in json.loads(truth)["records"]:
            if tag["record_type"] == "TAG" and tag["tag_family"] == "tag36h11":
                labels[tag["image_id"]].append(
                    label(tag["tag_id"], tag["corners"], not tag["eval_complete"])
                )

        seen = set()
        for shard in sorted(source.glob("train-*.parquet")):
            for batch in pq.ParquetFile(shard).iter_batches(
                batch_size=1, columns=["image_id", "image"]
            ):
                row = batch.to_pylist()[0]
                name, image = row["image_id"], row["image"]["bytes"]
                if (
                    name in seen
                    or hashlib.sha256(image).hexdigest()
                    != checksums[f"images/{name}.png"]
                ):
                    raise ValueError(
                        f"Duplicate or corrupt Locus image: {campaign}/{name}"
                    )
                seen.add(name)
                yield campaign, name, image, labels.get(name, [])
        if len(seen) != expected or labels.keys() - seen:
            raise ValueError(
                f"Incomplete Locus campaign: {campaign} ({len(seen)}/{expected} frames)"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=("icra", "locus"))
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    frames = []
    load = icra_frames if args.dataset == "icra" else locus_frames
    for scenario, name, data, tags in load(args.source):
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError(f"Cannot decode {scenario}/{name}")
        height, width = image.shape
        file = f"{scenario}/{Path(name).name}.pgm"
        path = args.output / file
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            stream.write(f"P5\n{width} {height}\n255\n".encode())
            stream.write(image.tobytes())
        frames.append({"file": file, "scenario": scenario, "tags": tags})

    manifest = args.output / "truth.json"
    manifest.write_text(json.dumps(frames, allow_nan=False))
    print(f"Wrote {len(frames)} frames to {manifest}")


if __name__ == "__main__":
    main()
