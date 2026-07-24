import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.workers import stt_engine
from inspire_flow_backend.workers.stt_engine import (
    AudioTooLongError,
    DeviceUnavailableError,
    choose_device,
    create_sensevoice_engine,
)


@pytest.mark.parametrize(
    ("cuda_available", "mps_available", "expected"),
    [
        (True, True, "cuda"),
        (False, True, "mps"),
        (False, False, "cpu"),
    ],
)
def test_auto_device_prefers_cuda_then_mps_then_cpu(
    cuda_available: bool,
    mps_available: bool,
    expected: str,
) -> None:
    assert (
        choose_device(
            "auto",
            cuda_available=cuda_available,
            mps_available=mps_available,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("requested", "cuda_available", "mps_available"),
    [
        ("cuda", False, True),
        ("mps", True, False),
    ],
)
def test_explicit_accelerator_must_be_available(
    requested: str,
    cuda_available: bool,
    mps_available: bool,
) -> None:
    with pytest.raises(DeviceUnavailableError):
        choose_device(
            requested,
            cuda_available=cuda_available,
            mps_available=mps_available,
        )


@pytest.mark.parametrize("device", ["cpu", "cuda", "mps"])
def test_explicit_available_device_is_preserved(device: str) -> None:
    assert (
        choose_device(
            device,
            cuda_available=True,
            mps_available=True,
        )
        == device
    )


def fake_torch(*, cuda: bool, mps: bool) -> object:
    return SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: cuda),
        backends=SimpleNamespace(
            mps=SimpleNamespace(is_available=lambda: mps),
        ),
    )


def test_concrete_engine_loads_and_transcribes_only_through_lazy_modules(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_calls: list[dict[str, object]] = []

    class FakeModel:
        def generate(self, **kwargs: object):
            model_calls.append(kwargs)
            return [{"text": "<|zh|>测试正文", "language": "zh"}]

    class FakeAutoModel:
        def __new__(cls, **kwargs: object):
            model_calls.append(kwargs)
            return FakeModel()

    modules = {
        "torch": fake_torch(cuda=False, mps=True),
        "funasr": SimpleNamespace(AutoModel=FakeAutoModel),
        "funasr.utils.postprocess_utils": SimpleNamespace(
            rich_transcription_postprocess=lambda value: str(value).replace("<|zh|>", "")
        ),
        "soundfile": SimpleNamespace(
            info=lambda path: SimpleNamespace(frames=16_000, samplerate=16_000)
        ),
    }
    monkeypatch.setattr(stt_engine, "import_module", modules.__getitem__)
    settings = Settings(_env_file=None, stt_device="mps")

    engine = create_sensevoice_engine(settings)
    result = engine.transcribe(tmp_path / "voice.wav", language="zh", use_itn=True)

    assert engine.device == "mps"
    assert os.environ["HF_HUB_DISABLE_XET"] == "1"
    assert model_calls[0]["device"] == "mps"
    assert model_calls[0]["hub"] == "hf"
    assert model_calls[1]["input"] == str(tmp_path / "voice.wav")
    assert result.text == "测试正文"
    assert result.detected_language == "zh"
    assert result.duration_seconds == 1.0


def test_auto_device_retries_model_initialization_once_on_cpu(monkeypatch) -> None:
    devices: list[str] = []

    class FakeAutoModel:
        def __new__(cls, **kwargs: object):
            device = str(kwargs["device"])
            devices.append(device)
            if device == "mps":
                raise RuntimeError("unsupported MPS operation")
            return object()

    modules = {
        "torch": fake_torch(cuda=False, mps=True),
        "funasr": SimpleNamespace(AutoModel=FakeAutoModel),
        "funasr.utils.postprocess_utils": SimpleNamespace(rich_transcription_postprocess=str),
    }
    monkeypatch.setattr(stt_engine, "import_module", modules.__getitem__)

    engine = create_sensevoice_engine(Settings(_env_file=None, stt_device="auto"))

    assert engine.device == "cpu"
    assert devices == ["mps", "cpu"]


def test_duration_limit_is_checked_before_model_inference(
    monkeypatch,
    tmp_path: Path,
) -> None:
    generated = False

    class FakeModel:
        def generate(self, **kwargs: object):
            nonlocal generated
            generated = True
            return []

    modules = {
        "torch": fake_torch(cuda=False, mps=False),
        "funasr": SimpleNamespace(AutoModel=lambda **kwargs: FakeModel()),
        "funasr.utils.postprocess_utils": SimpleNamespace(rich_transcription_postprocess=str),
        "soundfile": SimpleNamespace(
            info=lambda path: SimpleNamespace(frames=301_000, samplerate=1_000)
        ),
    }
    monkeypatch.setattr(stt_engine, "import_module", modules.__getitem__)
    engine = create_sensevoice_engine(Settings(_env_file=None))

    with pytest.raises(AudioTooLongError):
        engine.transcribe(tmp_path / "long.wav", language="auto", use_itn=True)

    assert generated is False
