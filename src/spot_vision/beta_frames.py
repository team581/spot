"""Bounded shared snapshots and disposable previews; HTTP never captures/encodes."""

from __future__ import annotations

import base64
import copy
import threading
import time
from collections import deque


class FrameHub:
    def __init__(self, *, max_clients: int = 8, width: int = 960, fps: float = 8) -> None:
        self._lock = threading.RLock()
        self.latest, self.results, self.encoded = {}, {}, {}
        self.interests = {}
        self.max_clients, self.width, self.interval = max_clients, width, 1 / fps
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._encode, name="preview-encoder", daemon=True)
        self.last_progress = time.monotonic()
        self.fault = ""

    def retain(self, identities) -> None:
        """Bound snapshots to current devices and explicitly bound missing roles."""
        identities = set(identities)
        with self._lock:
            for mapping in (self.latest, self.results, self.encoded):
                for identity in set(mapping) - identities:
                    del mapping[identity]

    def capture(self, packet) -> None:
        with self._lock:
            self.latest[packet.camera_id] = packet

    def result(self, detected, solution) -> None:
        with self._lock:
            self.results[detected.frame.camera_id] = (detected, solution)

    def image(self, identity: str):
        with self._lock:
            return self.latest.get(identity)

    def preview(self, identity: str, client: str) -> dict:
        now = time.monotonic()
        with self._lock:
            self.interests = {
                key: value for key, value in self.interests.items() if now - value[1] < 3
            }
            if client not in self.interests and len(self.interests) >= self.max_clients:
                raise ValueError("Preview client limit reached")
            self.interests[client] = (identity, now)
            result = copy.deepcopy(self.encoded.get(identity, {"image": None, "tags": []}))
            captured = result.get("captured_monotonic_ns")
            result["age_s"] = None if captured is None else (time.monotonic_ns() - captured) / 1e9
            if result["age_s"] is None or result["age_s"] > 0.5:
                result["tags"], result["stale"] = [], True
            else:
                result["stale"] = False
            return result

    def _encode(self) -> None:
        import cv2

        order = deque()
        last = {}
        last_encode = 0.0
        while not self.stop_event.wait(0.01):
            self.last_progress = time.monotonic()
            with self._lock:
                interested = {
                    identity
                    for identity, stamp in self.interests.values()
                    if time.monotonic() - stamp < 3
                }
            order = deque(key for key in order if key in interested)
            order.extend(sorted(interested - set(order)))
            if not order:
                continue
            if time.monotonic() - last_encode < 1 / 16:
                continue
            identity = order.popleft()
            order.append(identity)
            if time.monotonic() - last.get(identity, 0) < self.interval:
                continue
            with self._lock:
                frame = self.latest.get(identity)
                processed = self.results.get(identity)
                if (
                    processed
                    and time.monotonic_ns() - processed[0].frame.captured_monotonic_ns < 500_000_000
                ):
                    frame = processed[0].frame
                if frame is None:
                    continue
                same = processed and processed[0].frame is frame
                tags = (
                    [
                        {
                            "id": tag.id,
                            **processed[1].tag_diagnostics.get(tag.id, {}),
                            "corners": tag.corners.tolist(),
                            "used": tag.id in processed[1].used_tag_ids,
                            "reason": processed[1].rejection_reasons.get(tag.id, ""),
                        }
                        for tag in processed[0].batch.detections
                    ]
                    if same
                    else []
                )
                candidates = (
                    [
                        {
                            "translation": c.translation.tolist(),
                            "quaternion": c.quaternion_wxyz.tolist(),
                            "method": int(c.method),
                            "ids": list(c.tag_ids),
                            "error_px": c.reprojection_error_px,
                            "distance_m": c.average_tag_distance_m,
                        }
                        for c in processed[1].candidates
                    ]
                    if same
                    else []
                )
            try:
                image = cv2.cvtColor(frame.image, cv2.COLOR_YUV2BGR_YUY2)
                scale = min(1.0, self.width / image.shape[1], 540 / image.shape[0])
                if scale < 1:
                    image = cv2.resize(
                        image, (round(image.shape[1] * scale), round(image.shape[0] * scale))
                    )
                ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if not ok or jpeg.nbytes > 512 * 1024:
                    raise ValueError("Preview encoding exceeded bound")
                result = {
                    "image": base64.b64encode(jpeg).decode(),
                    "sequence": frame.sequence,
                    "capture_epoch": frame.capture_epoch,
                    "generation": frame.runtime_generation,
                    "captured_monotonic_ns": frame.captured_monotonic_ns,
                    "width": frame.image.shape[1],
                    "height": frame.image.shape[0],
                    "processed": bool(same),
                    "tags": tags,
                    "candidates": candidates,
                }
                with self._lock:
                    self.encoded[identity] = result
                self.fault = ""
            except Exception as exc:  # noqa: BLE001 - isolate backend/job failures at the worker boundary
                self.fault = str(exc)
            last[identity] = time.monotonic()
            last_encode = last[identity]

    def start(self) -> None:
        self.worker.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.worker.is_alive():
            self.worker.join(timeout=2)
