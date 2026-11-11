import struct
import zlib

from backend.core.contracts import InputError  # first: applies the OpenCV env clamps before cv2 loads
from backend.core.imaging import IMAGE_KEYS, decode_image, encode_webp

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402


def _jpeg(w: int, h: int) -> bytes:
    img = np.random.default_rng(0).integers(0, 255, (h, w, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def test_image_keys():
    assert IMAGE_KEYS == ("selfie", "licence_front", "licence_back", "vehicle")


@pytest.mark.parametrize("bad", [b"", bytearray(), None, "text", 5])
def test_rejects_empty_or_wrong_type(bad):
    with pytest.raises(InputError) as e:
        decode_image(bad, 1000)
    assert e.value.code == "INVALID_IMAGE"


def test_rejects_empty_bytes():
    with pytest.raises(InputError) as e:
        decode_image(b"", 1000)
    assert e.value.code == "INVALID_IMAGE"


def test_rejects_random_bytes():
    data = np.random.default_rng(1).bytes(4096)
    with pytest.raises(InputError) as e:
        decode_image(data, 1000)
    assert e.value.code == "INVALID_IMAGE"


def test_rejects_truncated_jpeg():
    data = _jpeg(200, 200)
    try:
        out = decode_image(data[: len(data) // 2], 1000)
    except InputError as e:
        assert e.code == "INVALID_IMAGE"
    else:
        assert out.ndim == 3 and out.shape[2] == 3 and out.dtype == np.uint8


def test_rejects_pixel_bomb():
    # Valid 20000x20000 gray PNG streamed through zlib (cv2.imencode refuses this size under the clamp).
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    z = zlib.compressobj()
    row = bytes(20001)
    idat = b"".join(z.compress(row) for _ in range(20000)) + z.flush()
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 20000, 20000, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    with pytest.raises(InputError) as e:
        decode_image(png, 1000)
    assert e.value.code == "INVALID_IMAGE"


def test_downscales_long_side_to_max():
    out = decode_image(_jpeg(400, 200), 100)
    assert out.shape == (50, 100, 3)


def test_keeps_small_image_size():
    assert decode_image(_jpeg(60, 30), 100).shape == (30, 60, 3)


def test_grayscale_and_bgra_become_bgr():
    for arr in (np.zeros((20, 30), np.uint8), np.zeros((20, 30, 4), np.uint8)):
        ok, buf = cv2.imencode(".png", arr)
        out = decode_image(buf.tobytes(), 100)
        assert out.shape == (20, 30, 3) and out.dtype == np.uint8


def test_applies_exif_orientation():
    data = _jpeg(40, 20)
    tiff = (b"MM\x00\x2a\x00\x00\x00\x08" + struct.pack(">H", 1)
            + struct.pack(">HHI", 0x0112, 3, 1) + struct.pack(">HH", 6, 0) + b"\x00\x00\x00\x00")
    payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    out = decode_image(data[:2] + app1 + data[2:], 1000)
    assert out.shape == (40, 20, 3)


def test_encode_webp_roundtrip_and_errors():
    img = np.zeros((16, 16, 3), np.uint8)
    out = cv2.imdecode(np.frombuffer(encode_webp(img, 80), np.uint8), cv2.IMREAD_COLOR)
    assert out.shape == (16, 16, 3)
    with pytest.raises(InputError):
        encode_webp(np.zeros((0, 0, 3), np.uint8), 80)
