# ◈ COFM Save as Phone Photo

[![Telegram](https://img.shields.io/badge/Telegram-ComfyOFM-26A5E4?logo=telegram&logoColor=white)](https://t.me/ComfyOFM)

A single ComfyUI node that re-saves images as phone-camera JPEGs:

- **Phone sensor size.** 12MP (4032×3024 Apple, 4000×3000 Samsung), or 48/50MP on Pro Max and Ultra models. `Original` keeps your pixel size.
- **A faint ±1 dither** on every channel (toggle with `add_noise`).
- **A complete, standards-valid EXIF block** for the chosen phone: make, model, software, lens, exposure time, f-number, ISO, APEX values, capture time with sub-seconds and time-zone offset, an embedded thumbnail, and optional GPS. Every file passes `exiftool -validate`.

Phones: iPhone 11, iPhone 12 mini, iPhone 15 Pro Max, iPhone 16 Pro Max, Samsung Galaxy S24 Ultra, Samsung Galaxy S25 Ultra.

## Install

ComfyUI Manager → **Install via Git URL** → `https://github.com/CrispyVYJ/COFM_SaveAsPhonePhoto`, or:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/CrispyVYJ/COFM_SaveAsPhonePhoto
```

Restart ComfyUI. No extra pip packages: it uses only Pillow and numpy, which ComfyUI already ships.

The example workflow appears under **Templates → COFM_SaveAsPhonePhoto**, and is also in `example_workflows/`.

## Use

- **From a generation:** connect any `IMAGE` output to `images`. When `images` is connected, `folder` is ignored.
- **A folder of finished images:** put them in `ComfyUI/input/<folder>/`, leave `images` unconnected and pick the folder.

Output goes to `ComfyUI/output/<output_folder>/<filename_prefix>_00001.jpg` and onward. Existing files are never overwritten.

| Input | What it does |
|---|---|
| `folder` | Subfolder of `input/` to convert, or `(images input)` |
| `filename_prefix` | File name stem |
| `phone_model` | EXIF profile and sensor size |
| `resolution` | `12MP`, `48MP/50MP` (12MP on phones without it), or `Original` |
| `gps_location` | City for GPS tags and the time-zone offset. `Random US City` picks one per run. `None` writes no GPS and uses the computer's time zone |
| `output_folder` | Subfolder of `output/` |
| `quality` | JPEG quality |
| `add_noise` | ±1 dither |
| `fit` | `center crop` keeps proportions; `stretch` reproduces the original node's geometry |
| `seed` | Drives exposure, capture timing, GPS jitter and noise |

## Differences from the original Save as Phone Photo node

The first eight widgets keep the original names and order, so old workflows load with their values. What changed:

- **EXIF types are correct.** The original wrote ExposureTime, FNumber, FocalLength and the APEX values as pairs of 16-bit integers, not EXIF rationals. Readers showed "f/178 100", a 6765 mm focal length and a garbage aperture. This version writes every tag with its proper TIFF type.
- **ApertureValue / ShutterSpeedValue / BrightnessValue** are real APEX values derived from the chosen exposure, instead of copies of the f-number or zero.
- **Exposure is plausible.** ISO and shutter come from a simple phone auto-exposure model, so they agree with each other, instead of being independent random picks that allowed a 1-second handheld shot.
- **Time is consistent.** Capture times run forwards in file order and are always in the past. The OffsetTime tags match the GPS city's time zone, and GPS time is UTC, as the EXIF spec requires.
- **No stretching by default.** The original resized every image to exactly 4:3/3:4, so a square image was squashed 33% and a 2:3 portrait 9%. The default is now a center crop.
- **Byte order follows the vendor** (Apple big-endian, Samsung little-endian), the JFIF header Pillow adds is removed, and a 160×120 EXIF thumbnail is embedded.
- **Takes an IMAGE input**, never overwrites earlier files, and re-runs when the folder's contents change.
- **iPhone 16 Pro Max** lens string fixed ("triple", not "quad"); 35mm-equivalent focal lengths match each phone's main camera.

## Limits

- No Apple/Samsung MakerNote, no Display P3 ICC profile, and the output is JPEG, not HEIC.
- EXIF is metadata only. It does not change how the pixels look, and Content Credentials (C2PA) and AI-image detectors don't rely on it.

## Community

Questions, results and updates: join the Comfy OFM Telegram community at **[t.me/ComfyOFM](https://t.me/ComfyOFM)**.

## Tests

```bash
pip install pytest pillow numpy
pytest tests
```
