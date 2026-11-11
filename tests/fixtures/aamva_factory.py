"""Build AAMVA barcode text for tests. All values are fake."""
from __future__ import annotations

FAKE_FIELDS = {
    "DCA": "G",
    "DCB": "NONE",
    "DCD": "NONE",
    "DBA": "20301231",
    "DCS": "TESTER",
    "DAC": "ALEX",
    "DAD": "JAMIE",
    "DBD": "20230914",
    "DBB": "19900315",
    "DBC": "1",
    "DAY": "BRO",
    "DAU": "175 cm",
    "DAG": "1 TEST ST",
    "DAI": "TOWN",
    "DAJ": "ON",
    "DAK": "A1A1A1",
    "DAQ": "T12345678901234",
    "DCF": "FAKE0001",
    "DCG": "CAN",
}


def make_aamva_text(
    iin: str = "636012",
    version: str = "09",
    fields: dict[str, str] | None = None,
    extra_subfiles: dict[str, dict[str, str]] | None = None,
) -> str:
    fields = dict(FAKE_FIELDS if fields is None else fields)
    subfiles = [("DL", fields)] + list((extra_subfiles or {}).items())
    bodies = [t + "".join(f"{k}{v}\n" for k, v in f.items()) + "\r" for t, f in subfiles]
    juris = "00" if int(version) >= 2 else ""
    header_len = len("@\n\x1e\rANSI ") + 6 + 2 + len(juris) + 2 + 10 * len(subfiles)
    directory, offset = "", header_len
    for (t, _), body in zip(subfiles, bodies):
        directory += f"{t}{offset:04d}{len(body):04d}"
        offset += len(body)
    return f"@\n\x1e\rANSI {iin}{version}{juris}{len(subfiles):02d}{directory}" + "".join(bodies)


# ---- image rendering for decode tests ----
def render_card(text: str, scale: int = 3, canvas: tuple[int, int] = (1000, 1600), seed: int = 0):
    """A grey 'card back' with the PDF417 barcode and a Code128 decoy, as a BGR image."""
    import backend.core  # noqa: F401  (clamps before cv2)
    import cv2
    import numpy as np
    import zxingcpp

    rng = np.random.default_rng(seed)
    barcode = zxingcpp.create_barcode(text.encode("latin-1"), zxingcpp.BarcodeFormat.PDF417)
    bar = np.array(zxingcpp.write_barcode_to_image(barcode, scale=scale))
    decoy = np.array(
        zxingcpp.write_barcode_to_image(
            zxingcpp.create_barcode("1462949", zxingcpp.BarcodeFormat.Code128), scale=2
        )
    )
    img = np.full(canvas, 200, np.uint8)
    img = np.clip(img + rng.normal(0, 6, canvas), 0, 255).astype(np.uint8)
    y0, x0 = canvas[0] // 2, (canvas[1] - bar.shape[1]) // 2
    img[y0 : y0 + bar.shape[0], x0 : x0 + bar.shape[1]] = bar
    dh, dw = decoy.shape
    img[40 : 40 + dh, 60 : 60 + dw] = decoy
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def distort(img, kind: str):
    import backend.core  # noqa: F401
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    if kind == "blur":
        return cv2.GaussianBlur(img, (5, 5), 1.2)
    if kind == "rotate90":
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if kind == "perspective":
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        dst = np.float32([[w * 0.03, h * 0.02], [w * 0.97, 0], [w, h * 0.98], [0, h]])
        return cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=(200, 200, 200))
    if kind == "dark":
        noise = np.random.default_rng(1).normal(0, 5, img.shape)
        return np.clip(img.astype(np.float32) * 0.35 + noise, 0, 255).astype(np.uint8)
    if kind == "small":
        return cv2.resize(img, None, fx=0.7, fy=0.7, interpolation=cv2.INTER_AREA)
    raise ValueError(kind)
