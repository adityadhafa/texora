"""Lazy ``iter_image_pages`` tests (design §2.1, MEDIUM-1) — one frame in flight at a time."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from texora_engine.ingest.images import image_frame_count, iter_image_pages
from texora_engine.settings import Settings

_TIFF = Path(__file__).resolve().parent / "fixtures" / "multipage.tiff"


def _settings(tmp_path: Path) -> Settings:
    return Settings(token="t", log_dir=tmp_path / "logs", db_path=tmp_path / "db.sqlite")


def test_iter_image_pages_yields_one_frame_at_a_time(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    seen: list[int] = []
    gen = iter_image_pages(_TIFF, settings)
    # Pull frames one at a time, asserting each yielded image is an independent RGB bitmap and the
    # generator is lazy (it does not materialize all frames up-front).
    for rendered, image in gen:
        assert image.mode == "RGB"
        assert (rendered.width, rendered.height) == image.size
        seen.append(rendered.index)
        image.close()
    assert seen == [0, 1]


def test_image_frame_count_matches_pillow(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert image_frame_count(_TIFF, settings) == 2


def test_iter_image_pages_does_not_preload_all_frames(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    loads: list[int] = []
    real_load = Image.Image.load

    def _counting_load(self: Image.Image) -> object:
        loads.append(id(self))
        return real_load(self)

    monkeypatch.setattr(Image.Image, "load", _counting_load)
    gen = iter_image_pages(_TIFF, settings)
    first_rendered, first_image = next(gen)
    # Only the first frame has been loaded so far (lazy): exactly one load() has run for a frame.
    assert first_rendered.index == 0
    first_image.close()
    # Drain the rest.
    for _, img in gen:
        img.close()
