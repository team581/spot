from types import SimpleNamespace

import pytest

import spot_vision


@pytest.fixture
def cuda_native(monkeypatch):
    """Exercise CUDA selection and fallback without requiring native code or a GPU."""

    def unexpected_cuda(*args):
        pytest.fail("unexpected CUDA construction")

    module = SimpleNamespace(
        CUDA_AVAILABLE=True,
        DetectorOptions=SimpleNamespace,
        CameraMatrix=SimpleNamespace,
        DistortionCoefficients=SimpleNamespace,
        CudaDetector=unexpected_cuda,
    )
    monkeypatch.setattr(spot_vision, "_spot_cuda", module, raising=False)
    return module
