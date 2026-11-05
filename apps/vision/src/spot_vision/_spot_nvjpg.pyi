"""Jetson NVJPG MJPEG decoder."""

import numpy as np

class NvjpgDecoder:
    def __init__(self) -> None: ...
    def decode(self, data: bytes) -> np.ndarray:
        """Decode a JPEG and return its (height, width) uint8 luma plane."""
