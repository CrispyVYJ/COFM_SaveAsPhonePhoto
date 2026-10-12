"""
◈ COFM Save as Phone Photo.

Re-saves images as JPEGs that read like a handset capture: phone sensor size,
a faint ±1 dither, and an EXIF block for the chosen phone (make, model, lens,
exposure, timestamps, optional GPS).

The first eight widgets keep the order and names of the original node, so a
workflow saved against it loads with its values intact. Everything after
`add_noise` is new.
"""

import io
import logging
import math
import os
import random
import re
from datetime import datetime, timedelta, timezone
from fractions import Fraction

import numpy as np
from PIL import Image, ImageOps

import folder_paths

from .cofm_theme import CofmNodeMixin
from .exif_writer import (
    ASCII, BYTE, LONG, RATIONAL, SHORT, SRATIONAL, UNDEFINED,
    build_tiff, jpeg_with_exif,
)

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None


USE_IMAGES_INPUT = "(images input)"

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# focal_length / f_number are exact EXIF rationals. focal_35mm is what the
# phone itself reports for its main camera. big_endian follows the vendor:
# Apple writes Motorola (MM) byte order, Samsung writes Intel (II).
PHONE_PROFILES = {
    "iPhone 11": {
        "make": "Apple", "model": "iPhone 11", "software": "17.5.1",
        "lens_model": "iPhone 11 back dual wide camera 4.25mm f/1.8",
        "focal_length": (425, 100), "f_number": (18, 10), "focal_35mm": 26,
        "iso_range": (32, 1600), "max_shutter": 4000, "big_endian": True,
        "resolutions": {"12MP": (4032, 3024)},
    },
    "iPhone 12 mini": {
        "make": "Apple", "model": "iPhone 12 mini", "software": "17.5.1",
        "lens_model": "iPhone 12 mini back dual wide camera 4.2mm f/1.6",
        "focal_length": (42, 10), "f_number": (16, 10), "focal_35mm": 26,
        "iso_range": (32, 1600), "max_shutter": 4000, "big_endian": True,
        "resolutions": {"12MP": (4032, 3024)},
    },
    "iPhone 15 Pro Max": {
        "make": "Apple", "model": "iPhone 15 Pro Max", "software": "17.5.1",
        "lens_model": "iPhone 15 Pro Max back triple camera 6.765mm f/1.78",
        "focal_length": (6765, 1000), "f_number": (178, 100), "focal_35mm": 24,
        "iso_range": (50, 1600), "max_shutter": 4000, "big_endian": True,
        "resolutions": {"12MP": (4032, 3024), "48MP": (8064, 6048)},
    },
    "iPhone 16 Pro Max": {
        "make": "Apple", "model": "iPhone 16 Pro Max", "software": "18.3.1",
        "lens_model": "iPhone 16 Pro Max back triple camera 6.765mm f/1.78",
        "focal_length": (6765, 1000), "f_number": (178, 100), "focal_35mm": 24,
        "iso_range": (50, 1600), "max_shutter": 4000, "big_endian": True,
        "resolutions": {"12MP": (4032, 3024), "48MP": (8064, 6048)},
    },
    "Samsung Galaxy S24 Ultra": {
        "make": "samsung", "model": "SM-S928B", "software": "S928BXXS4AXL1",
        "lens_model": None,
        "focal_length": (630, 100), "f_number": (170, 100), "focal_35mm": 23,
        "iso_range": (50, 1600), "max_shutter": 3000, "big_endian": False,
        "resolutions": {"12MP": (4000, 3000), "50MP": (8160, 6120)},
    },
    "Samsung Galaxy S25 Ultra": {
        "make": "samsung", "model": "SM-S938B", "software": "S938BXXU1AXK5",
        "lens_model": None,
        "focal_length": (630, 100), "f_number": (170, 100), "focal_35mm": 23,
        "iso_range": (50, 1600), "max_shutter": 4000, "big_endian": False,
        "resolutions": {"12MP": (4000, 3000), "50MP": (8160, 6120)},
    },
}

RESOLUTIONS = ["12MP", "48MP/50MP", "Original"]
FITS = ["center crop", "stretch"]

# (latitude, longitude, altitude m, IANA zone, standard UTC offset in hours).
# The fixed offset is only used where the host has no tz database (Windows
# Python without the tzdata package); it ignores daylight saving.
_CITIES = {
    "New York":      (40.7128, -74.0060, 10, "America/New_York", -5),
    "Los Angeles":   (34.0522, -118.2437, 71, "America/Los_Angeles", -8),
    "London":        (51.5074, -0.1278, 11, "Europe/London", 0),
    "Tokyo":         (35.6762, 139.6503, 40, "Asia/Tokyo", 9),
    "Paris":         (48.8566, 2.3522, 35, "Europe/Paris", 1),
    "Sydney":        (-33.8688, 151.2093, 58, "Australia/Sydney", 10),
    "Melbourne":     (-37.8136, 144.9631, 31, "Australia/Melbourne", 10),
    "Dubai":         (25.2048, 55.2708, 5, "Asia/Dubai", 4),
    "Chicago":       (41.8781, -87.6298, 181, "America/Chicago", -6),
    "Houston":       (29.7604, -95.3698, 15, "America/Chicago", -6),
    "Phoenix":       (33.4484, -112.0740, 331, "America/Phoenix", -7),
    "San Antonio":   (29.4241, -98.4936, 198, "America/Chicago", -6),
    "San Diego":     (32.7157, -117.1611, 20, "America/Los_Angeles", -8),
    "Austin":        (30.2672, -97.7431, 149, "America/Chicago", -6),
    "San Francisco": (37.7749, -122.4194, 16, "America/Los_Angeles", -8),
    "Seattle":       (47.6062, -122.3321, 56, "America/Los_Angeles", -8),
    "Denver":        (39.7392, -104.9903, 1609, "America/Denver", -7),
    "Charlotte":     (35.2271, -80.8431, 229, "America/New_York", -5),
    "Nashville":     (36.1627, -86.7816, 182, "America/Chicago", -6),
    "Miami":         (25.7617, -80.1918, 2, "America/New_York", -5),
    "Washington DC": (38.9072, -77.0369, 22, "America/New_York", -5),
}

_RANDOM_US = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "San Antonio",
    "San Diego", "Austin", "San Francisco", "Seattle", "Denver", "Charlotte",
    "Nashville", "Miami", "Washington DC",
]

GPS_CHOICES = ["None", "New York", "Los Angeles", "London", "Tokyo", "Paris",
               "Sydney", "Melbourne", "Dubai", "Random US City"]

_SHUTTER_DENOMS = [15, 20, 25, 30, 40, 50, 60, 80, 100, 120, 125, 160, 200, 250,
                   320, 400, 500, 640, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000]
_ISO_STEPS = [25, 32, 40, 50, 64, 80, 100, 125, 160, 200, 250, 320, 400, 500,
              640, 800, 1000, 1250, 1600, 2000, 2500, 3200]
# Slowest shutter phone auto-exposure holds handheld before it raises ISO.
_HANDHELD_LIMIT = 1 / 60


# ---------- small helpers ----------

def _rational(x, limit=100000):
    f = Fraction(x).limit_denominator(limit)
    return (f.numerator, f.denominator)


def _dms(decimal_deg):
    d = abs(decimal_deg)
    degrees = int(d)
    minutes = int((d - degrees) * 60)
    seconds = round((d - degrees - minutes / 60) * 3600 * 100)
    return [(degrees, 1), (minutes, 1), (seconds, 100)]


def _offset_str(dt):
    off = dt.utcoffset() or timedelta(0)
    sign = "-" if off < timedelta(0) else "+"
    minutes = abs(int(off.total_seconds())) // 60
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _zone(city):
    _, _, _, name, fixed = _CITIES[city]
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - no tz database on this host
            pass
    return timezone(timedelta(hours=fixed))


def _input_subfolders():
    getter = getattr(folder_paths, "get_input_subfolders", None)
    if getter is not None:
        return list(getter())
    root = folder_paths.get_input_directory()
    return sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))


def _folder_files(folder):
    root = os.path.join(folder_paths.get_input_directory(), folder)
    if not os.path.isdir(root):
        raise RuntimeError(f"Folder not found: {root}")
    files = sorted(
        os.path.join(root, f) for f in os.listdir(root)
        if os.path.splitext(f)[1].lower() in _IMAGE_EXTENSIONS
    )
    if not files:
        raise RuntimeError(f"No images found in {root}")
    return files


def _output_dir(output_folder):
    root = os.path.realpath(folder_paths.get_output_directory())
    out = os.path.realpath(os.path.join(root, output_folder.strip() or "phone_photos"))
    if os.path.commonpath([root, out]) != root:
        raise ValueError(f"output_folder must stay inside the output directory: {output_folder!r}")
    os.makedirs(out, exist_ok=True)
    sub = os.path.relpath(out, root)
    return out, "" if sub == "." else sub


def _next_counter(out_dir, prefix):
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)\.jpg$", re.IGNORECASE)
    numbers = [int(m.group(1)) for m in map(pattern.match, os.listdir(out_dir)) if m]
    return max(numbers, default=0) + 1


# ---------- exposure, time, place ----------

def _pick_exposure(rng, profile):
    """A shutter/ISO pair a phone's auto-exposure would plausibly choose.

    Draws a scene brightness, holds base ISO until the shutter would drop
    below 1/60 s, then raises ISO, like handset AE. The pair is therefore
    consistent with the aperture, and BrightnessValue can be derived from it.
    """
    n = profile["f_number"][0] / profile["f_number"][1]
    iso_lo, iso_hi = profile["iso_range"]
    ev100 = rng.uniform(6.0, 14.5)  # dim interior .. bright daylight

    t = n * n * 100 / (iso_lo * 2 ** ev100)
    iso = iso_lo
    if t > _HANDHELD_LIMIT:
        iso = min(iso_hi, iso_lo * t / _HANDHELD_LIMIT)
        t = n * n * 100 / (iso * 2 ** ev100)

    denoms = [d for d in _SHUTTER_DENOMS if d <= profile["max_shutter"]]
    denom = min(denoms, key=lambda d: abs(math.log2(d * t)))
    iso_exact = n * n * 100 * denom / 2 ** ev100
    steps = [s for s in _ISO_STEPS if iso_lo <= s <= iso_hi]
    iso = min(steps, key=lambda s: abs(math.log2(s / iso_exact)))
    return denom, iso


def _shot_times(rng, count, tz):
    """Capture times in shooting order, all in the past, seconds apart."""
    gaps = [0] + [rng.randint(3, 45) for _ in range(count - 1)]
    lead = rng.randint(30, 900)
    now = datetime.now(timezone.utc)
    start = now - timedelta(seconds=sum(gaps) + lead)
    times, t = [], start
    for gap in gaps:
        t += timedelta(seconds=gap)
        times.append(t.astimezone(tz))
    return times


def _resolve_city(rng, gps_location):
    if gps_location == "None":
        return None
    if gps_location == "Random US City":
        return rng.choice(_RANDOM_US)
    return gps_location


# ---------- EXIF ----------

def build_phone_exif(profile, width, height, shot, rng, city=None, thumbnail=None):
    """Return the TIFF stream for one photo."""
    denom, iso = _pick_exposure(rng, profile)
    n = profile["f_number"][0] / profile["f_number"][1]
    av = 2 * math.log2(n)
    tv = math.log2(denom)
    sv = math.log2(iso / 3.125)
    stamp = shot.strftime("%Y:%m:%d %H:%M:%S")
    offset = _offset_str(shot)
    subsec = f"{rng.randint(0, 999):03d}"

    ifd0 = [
        (0x010F, ASCII, profile["make"]),
        (0x0110, ASCII, profile["model"]),
        (0x0112, SHORT, 1),              # Orientation: normal
        (0x011A, RATIONAL, (72, 1)),     # XResolution
        (0x011B, RATIONAL, (72, 1)),     # YResolution
        (0x0128, SHORT, 2),              # ResolutionUnit: inches
        (0x0131, ASCII, profile["software"]),
        (0x0132, ASCII, stamp),          # DateTime
        (0x0213, SHORT, 1),              # YCbCrPositioning: centred
    ]

    exif = [
        (0x829A, RATIONAL, (1, denom)),           # ExposureTime
        (0x829D, RATIONAL, profile["f_number"]),  # FNumber
        (0x8822, SHORT, 2),                       # ExposureProgram: normal
        (0x8827, SHORT, iso),                     # ISOSpeedRatings
        (0x9000, UNDEFINED, b"0232"),             # ExifVersion
        (0x9003, ASCII, stamp),                   # DateTimeOriginal
        (0x9004, ASCII, stamp),                   # DateTimeDigitized
        (0x9010, ASCII, offset),                  # OffsetTime
        (0x9011, ASCII, offset),                  # OffsetTimeOriginal
        (0x9012, ASCII, offset),                  # OffsetTimeDigitized
        (0x9101, UNDEFINED, b"\x01\x02\x03\x00"), # ComponentsConfiguration: YCbCr
        (0x9201, SRATIONAL, _rational(tv)),       # ShutterSpeedValue (APEX)
        (0x9202, RATIONAL, _rational(av)),        # ApertureValue (APEX)
        (0x9203, SRATIONAL, _rational(av + tv - sv)),  # BrightnessValue (APEX)
        (0x9204, SRATIONAL, (0, 1)),              # ExposureBiasValue
        (0x9207, SHORT, 5),                       # MeteringMode: pattern
        (0x9209, SHORT, 0x10),                    # Flash: off, did not fire
        (0x920A, RATIONAL, profile["focal_length"]),
        (0x9291, ASCII, subsec),                  # SubSecTimeOriginal
        (0x9292, ASCII, subsec),                  # SubSecTimeDigitized
        (0xA000, UNDEFINED, b"0100"),             # FlashpixVersion
        (0xA001, SHORT, 1),                       # ColorSpace: sRGB
        (0xA002, LONG, width),                    # PixelXDimension
        (0xA003, LONG, height),                   # PixelYDimension
        (0xA217, SHORT, 2),                       # SensingMethod: one-chip colour area
        (0xA301, UNDEFINED, b"\x01"),             # SceneType: directly photographed
        (0xA402, SHORT, 0),                       # ExposureMode: auto
        (0xA403, SHORT, 0),                       # WhiteBalance: auto
        (0xA405, SHORT, profile["focal_35mm"]),   # FocalLengthIn35mmFilm
        (0xA406, SHORT, 0),                       # SceneCaptureType: standard
    ]
    if profile["lens_model"]:
        exif += [
            (0xA433, ASCII, profile["make"]),        # LensMake
            (0xA434, ASCII, profile["lens_model"]),  # LensModel
        ]

    gps = None
    if city:
        lat, lon, alt = _CITIES[city][:3]
        # ±0.001° ≈ ±100 m, so a set is not pinned to one exact point.
        lat += rng.uniform(-0.001, 0.001)
        lon += rng.uniform(-0.001, 0.001)
        utc = shot.astimezone(timezone.utc)
        gps = [
            (0x0000, BYTE, b"\x02\x03\x00\x00"),      # GPSVersionID 2.3.0.0 (needed for GPSHPositioningError)
            (0x0001, ASCII, "N" if lat >= 0 else "S"),
            (0x0002, RATIONAL, _dms(lat)),
            (0x0003, ASCII, "E" if lon >= 0 else "W"),
            (0x0004, RATIONAL, _dms(lon)),
            (0x0005, BYTE, b"\x00"),                  # GPSAltitudeRef: above sea level
            (0x0006, RATIONAL, _rational(max(alt, 0) + rng.uniform(0, 6), 100)),
            # GPS time is UTC by definition, not the local capture time.
            (0x0007, RATIONAL, [(utc.hour, 1), (utc.minute, 1), (utc.second, 1)]),
            (0x001D, ASCII, utc.strftime("%Y:%m:%d")),  # GPSDateStamp
        ]
        if profile["make"] == "Apple":
            gps.append((0x001F, RATIONAL, _rational(rng.uniform(3, 35), 100)))  # GPSHPositioningError

    thumb_ifd = [
        (0x0103, SHORT, 6),           # Compression: JPEG
        (0x011A, RATIONAL, (72, 1)),
        (0x011B, RATIONAL, (72, 1)),
        (0x0128, SHORT, 2),
    ]
    return build_tiff(profile["big_endian"], ifd0, exif, gps,
                      thumb_ifd=thumb_ifd, thumbnail=thumbnail)


# ---------- pixels ----------

def _phone_size(img, profile, resolution, fit):
    if resolution == "Original":
        return img
    sizes = profile["resolutions"]
    if resolution == "12MP":
        target = sizes["12MP"]
    else:
        target = sizes.get("48MP") or sizes.get("50MP")
        if target is None:
            logging.warning("COFM_SaveAsPhonePhoto: %s has no 48/50MP mode, using 12MP", profile["model"])
            target = sizes["12MP"]

    w, h = img.size
    tw, th = target
    if fit == "stretch":
        # The original node's geometry, kept exactly: squares go landscape.
        if h > w:
            tw, th = th, tw
        return img.resize((tw, th), Image.LANCZOS)
    # Crop rather than distort. Squares go portrait, which keeps heads in frame.
    if h >= w:
        tw, th = th, tw
    return ImageOps.fit(img, (tw, th), Image.LANCZOS, centering=(0.5, 0.5))


def _thumbnail(img):
    w, h = img.size
    size = (160, 120) if w >= h else (120, 160)
    thumb = ImageOps.fit(img, size, Image.LANCZOS)
    buf = io.BytesIO()
    thumb.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _tensor_to_pil(image):
    arr = image.cpu().numpy()
    arr = np.clip(np.rint(arr * 255.0), 0, 255).astype(np.uint8)
    if arr.ndim == 3 and arr.shape[-1] == 4:
        arr = arr[..., :3]
    if arr.ndim == 2 or arr.shape[-1] == 1:
        return Image.fromarray(arr.squeeze(), "L").convert("RGB")
    return Image.fromarray(arr, "RGB")


# ---------- the node ----------

class COFM_SaveAsPhonePhoto(CofmNodeMixin):
    COFM_SECTION = "Image"
    COFM_TITLE = "Save as Phone Photo"
    COFM_SUMMARY = (
        "Saves images as JPEGs with phone-camera size and EXIF so they read as a handset capture."
    )
    COFM_PARAMS = {
        "images": "optional; when connected it is used and folder is ignored",
        "folder": "subfolder of input/ to batch-convert",
        "phone_model": "whose EXIF profile and sensor size to use",
        "resolution": "sensor size; Original keeps pixel dimensions",
        "gps_location": "city for GPS tags and the timezone offset",
        "quality": "JPEG quality",
        "add_noise": "±1 dither on every channel",
        "fit": "center crop keeps proportions; stretch is the old behaviour",
        "seed": "drives exposure, timing, GPS jitter and noise",
    }
    COFM_NOTE = "Files go to output/<output_folder>/<prefix>_00001.jpg and never overwrite."

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder": ([USE_IMAGES_INPUT] + _input_subfolders(), {
                    "tooltip": "Subfolder of input/ to convert. Ignored when images is connected."}),
                "filename_prefix": ("STRING", {"default": "ComfyUI"}),
                "phone_model": (list(PHONE_PROFILES), {"default": "iPhone 15 Pro Max"}),
                "resolution": (RESOLUTIONS, {"default": "12MP"}),
                "gps_location": (GPS_CHOICES, {"default": "Random US City"}),
                "output_folder": ("STRING", {"default": "phone_photos"}),
                "quality": ("INT", {"default": 95, "min": 1, "max": 100, "step": 1}),
            },
            "optional": {
                "add_noise": ("BOOLEAN", {"default": True}),
                "fit": (FITS, {"default": "center crop",
                               "tooltip": "center crop keeps proportions; stretch reproduces the original node"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF,
                                 "control_after_generate": True}),
                "images": ("IMAGE",),
            },
        }

    @classmethod
    def IS_CHANGED(cls, folder=USE_IMAGES_INPUT, **kwargs):
        # A folder's contents can change without any widget changing.
        if folder == USE_IMAGES_INPUT:
            return ""
        root = os.path.join(folder_paths.get_input_directory(), folder)
        try:
            return "|".join(
                f"{f}:{os.path.getmtime(os.path.join(root, f))}" for f in sorted(os.listdir(root))
            )
        except OSError:
            return float("nan")

    def save(self, folder, filename_prefix="ComfyUI", phone_model="iPhone 15 Pro Max",
             resolution="12MP", gps_location="Random US City", output_folder="phone_photos",
             quality=95, add_noise=True, fit="center crop", seed=0, images=None):
        if images is not None:
            sources = [lambda i=i: _tensor_to_pil(images[i]) for i in range(images.shape[0])]
            origin = "images input"
        elif folder != USE_IMAGES_INPUT:
            sources = [lambda p=p: Image.open(p).convert("RGB") for p in _folder_files(folder)]
            origin = f"input/{folder}"
        else:
            raise ValueError("Connect images, or pick an input subfolder in 'folder'.")

        profile = PHONE_PROFILES[phone_model]
        rng = random.Random(seed)
        noise_rng = np.random.default_rng(seed)
        city = _resolve_city(rng, gps_location)
        tz = _zone(city) if city else datetime.now().astimezone().tzinfo
        shots = _shot_times(rng, len(sources), tz)

        out_dir, subfolder = _output_dir(output_folder)
        prefix = filename_prefix.strip() or "ComfyUI"
        counter = _next_counter(out_dir, prefix)

        results = []
        for load, shot in zip(sources, shots):
            img = _phone_size(load(), profile, resolution, fit)
            if add_noise:
                arr = np.asarray(img, dtype=np.int16)
                arr = arr + noise_rng.integers(-1, 2, size=arr.shape, dtype=np.int16)
                img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")

            w, h = img.size
            tiff = build_phone_exif(profile, w, h, shot, rng, city=city, thumbnail=_thumbnail(img))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=int(quality))

            name = f"{prefix}_{counter:05d}.jpg"
            with open(os.path.join(out_dir, name), "wb") as fh:
                fh.write(jpeg_with_exif(buf.getvalue(), tiff))
            results.append({"filename": name, "subfolder": subfolder, "type": "output"})
            counter += 1

        logging.info("COFM_SaveAsPhonePhoto: saved %d image(s) from %s -> output/%s",
                     len(results), origin, subfolder)
        return {"ui": {"images": results}}
