"""Tests for COFM Save as Phone Photo. Runs without ComfyUI: only folder_paths is stubbed."""

import importlib.util
import math
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from PIL.ExifTags import IFD

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def pack(tmp_path, monkeypatch):
    fp = types.ModuleType("folder_paths")
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()
    fp.get_input_directory = lambda: str(tmp_path / "input")
    fp.get_output_directory = lambda: str(tmp_path / "output")
    fp.get_input_subfolders = lambda: sorted(p.name for p in (tmp_path / "input").iterdir() if p.is_dir())
    monkeypatch.setitem(sys.modules, "folder_paths", fp)

    # A fresh package name per test, so submodules re-import against this
    # test's folder_paths instead of a cached one from an earlier test.
    spec = importlib.util.spec_from_file_location(
        f"cofm_phone_photo_{uuid.uuid4().hex}", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    mod.tmp = tmp_path
    mod.pp = sys.modules[f"{spec.name}.phone_photo"]
    return mod


def _disc(path, w, h):
    im = Image.new("RGB", (w, h), (120, 140, 160))
    r = min(w, h) // 3
    ImageDraw.Draw(im).ellipse([w // 2 - r, h // 2 - r, w // 2 + r, h // 2 + r], fill=(230, 200, 180))
    im.save(path)


def _folder(pack, sizes):
    d = pack.tmp / "input" / "set"
    d.mkdir()
    for i, (w, h) in enumerate(sizes):
        _disc(d / f"{i:02d}.png", w, h)
    return "set"


def _run(pack, **kw):
    node = pack.NODE_CLASS_MAPPINGS["COFM_SaveAsPhonePhoto"]()
    args = dict(folder="set", seed=7)
    args.update(kw)
    ui = node.save(**args)["ui"]["images"]
    return [pack.tmp / "output" / r["subfolder"] / r["filename"] for r in ui]


def _exif(path):
    im = Image.open(path)
    ex = im.getexif()
    return im, ex, ex.get_ifd(IFD.Exif), ex.get_ifd(IFD.GPSInfo)


def _disc_aspect(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(int)
    ys, xs = np.nonzero(a[..., 0] > 200)
    return (xs.max() - xs.min()) / (ys.max() - ys.min())


def test_widget_order_matches_original_node(pack):
    spec = pack.NODE_CLASS_MAPPINGS["COFM_SaveAsPhonePhoto"].INPUT_TYPES()
    names = list(spec["required"]) + list(spec["optional"])
    assert names[:8] == ["folder", "filename_prefix", "phone_model", "resolution",
                         "gps_location", "output_folder", "quality", "add_noise"]


def test_exposure_tags_are_real_rationals_and_apex_consistent(pack):
    _folder(pack, [(832, 1216)] * 4)
    for path in _run(pack):
        _, _, ex, _ = _exif(path)
        n, t, iso = float(ex[0x829D]), float(ex[0x829A]), ex[0x8827]
        assert n == pytest.approx(1.78)
        assert float(ex[0x920A]) == pytest.approx(6.765)
        assert 0 < t <= 1 / 15
        assert float(ex[0x9202]) == pytest.approx(2 * math.log2(n), abs=1e-3)
        assert float(ex[0x9201]) == pytest.approx(-math.log2(t), abs=1e-3)
        bv = 2 * math.log2(n) - math.log2(t) - math.log2(iso / 3.125)
        assert float(ex[0x9203]) == pytest.approx(bv, abs=1e-3)


def test_byte_order_follows_vendor_and_no_jfif(pack):
    _folder(pack, [(832, 1216)])
    for model, head in (("iPhone 15 Pro Max", b"MM"), ("Samsung Galaxy S24 Ultra", b"II")):
        data = _run(pack, phone_model=model)[0].read_bytes()
        assert data[2:4] == b"\xff\xe1" and data[6:12] == b"Exif\0\0"
        assert data[12:14] == head
        assert b"JFIF\0" not in data[:64]


def test_center_crop_keeps_proportions_and_stretch_matches_original(pack):
    _folder(pack, [(832, 1216), (1024, 1024), (1216, 832)])
    crop = _run(pack, fit="center crop", output_folder="crop")
    assert [Image.open(p).size for p in crop] == [(3024, 4032), (3024, 4032), (4032, 3024)]
    for p in crop:
        assert _disc_aspect(p) == pytest.approx(1.0, abs=0.01)
    stretch = _run(pack, fit="stretch", output_folder="stretch")
    assert [Image.open(p).size for p in stretch] == [(3024, 4032), (4032, 3024), (4032, 3024)]


def test_pixel_dimension_tags_match_file(pack):
    _folder(pack, [(832, 1216)])
    for res in ("12MP", "Original"):
        im, _, ex, _ = _exif(_run(pack, resolution=res)[0])
        assert (ex[0xA002], ex[0xA003]) == im.size


def test_48mp_falls_back_to_12mp_on_phones_without_it(pack):
    _folder(pack, [(832, 1216)])
    assert Image.open(_run(pack, phone_model="iPhone 11", resolution="48MP/50MP")[0]).size == (3024, 4032)


def test_reruns_never_overwrite(pack):
    _folder(pack, [(64, 64)] * 2)
    first = _run(pack, resolution="Original")
    second = _run(pack, resolution="Original")
    assert {p.name for p in first}.isdisjoint({p.name for p in second})
    assert all(p.exists() for p in first + second)


def test_capture_times_are_ordered_past_and_gps_time_is_utc(pack):
    _folder(pack, [(64, 64)] * 5)
    paths = _run(pack, resolution="Original", gps_location="Tokyo")
    times = []
    for p in paths:
        _, _, ex, gps = _exif(p)
        local = datetime.strptime(ex[0x9003], "%Y:%m:%d %H:%M:%S")
        sign = -1 if ex[0x9011][0] == "-" else 1
        hh, mm = map(int, ex[0x9011][1:].split(":"))
        utc = local - sign * timedelta(hours=hh, minutes=mm)
        h, m, s = (int(float(v)) for v in gps[7])
        assert (utc.hour, utc.minute, utc.second) == (h, m, s)
        assert gps[29] == utc.strftime("%Y:%m:%d")
        assert ex[0x9011] == "+09:00"
        times.append(utc.replace(tzinfo=timezone.utc))
    assert times == sorted(times)
    assert times[-1] <= datetime.now(timezone.utc)


def test_images_input_wins_over_folder(pack):
    torch_like = types.SimpleNamespace
    batch = np.random.default_rng(0).random((2, 96, 64, 3), dtype=np.float32)

    class Batch:
        shape = batch.shape

        def __getitem__(self, i):
            return torch_like(cpu=lambda: torch_like(numpy=lambda: batch[i]))

    _folder(pack, [(32, 32)] * 3)
    paths = _run(pack, folder="set", images=Batch(), resolution="Original")
    assert [Image.open(p).size for p in paths] == [(64, 96), (64, 96)]


def test_output_folder_cannot_escape_output_dir(pack):
    _folder(pack, [(64, 64)])
    with pytest.raises(ValueError):
        _run(pack, output_folder="../escaped")


def test_no_images_and_no_folder_is_a_clear_error(pack):
    with pytest.raises(ValueError, match="Connect images"):
        _run(pack, folder="(images input)")
