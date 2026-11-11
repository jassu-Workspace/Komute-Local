# Stage 3: Vehicle plate and colour

Code: `backend/core/stages/vehicle.py`, `backend/core/matching.py`. Runs only when Stage 1 passed.

## Plate detection

YOLOv9-tiny at 384×384. Preprocessing: letterbox (pad value 114), RGB, `/255`, NCHW. The graph includes NMS, so the output rows are `[batch, x1, y1, x2, y2, class, score]` in letterboxed pixels (inferred and checked; see `docs/MODEL_FACTS.md`). Rows below score 0.35 are dropped, the best box is clipped to the image, and the crop gets an 8% margin. No plate gives `PLATE_NOT_FOUND` (retryable).

## Plate reading

`cct-xs-v2-global-model` (`cct_xs_v2_global.onnx`, 3.2 MB, MIT): a compact convolutional transformer trained on licence plates. It replaces the general-purpose PP-OCRv5 text model, which read only 1 of 9 real Canadian plates exactly (dropped characters, emblems read as characters, `W` read as `N`).

- **Input:** the whole plate crop (8% margin), resized to 128×64, RGB, `uint8`, NHWC `[1, 64, 128, 3]`. No normalisation.
- **Output `plate`:** `[1, 10, 37]` probabilities (softmax). Ten independent character slots, each choosing one of 37 classes: `0–9`, `A–Z` and `_` (empty slot). This is positional classification, not CTC: a repeated letter (`AAA 0000`) sits in separate slots and cannot collapse, and an emblem is simply not a character.
- **Output `region`:** `[1, 66]` country or region class. Not used.
- **Text:** the best class of each slot, empty slots dropped. **Confidence:** the lowest slot probability, so one unsure character makes the whole read unsure (an average would hide it).

An empty read or a confidence below 0.6 gives `PLATE_UNREADABLE` (retryable), not a mismatch.

## Plate rule

After removing everything but `A–Z` and `0–9`, the read matches the claimed plate if the strings are equal, or if they have equal length and differ in exactly one position and that pair is `O/0`, `I/1` or `B/8`. Anything else gives `PLATE_MISMATCH` (final).

## Colour (advisory only)

Four patches next to the plate (above, below, left, right) are converted to CIELAB. Pixels with L\* between 5 and 99 are kept, K-means (K = 3, fixed seed) finds the dominant cluster, and the nearest of 14 reference colours (CIE76) is the result. The spec's L\* > 92 glare cutoff was changed to 99, because the spec's own white reference is L\* 96 and white cars would have been discarded.

A mismatch adds advisory `COLOUR_MISMATCH`. An unknown claimed colour or too few pixels adds `COLOUR_UNVERIFIED`. Colour never blocks approval.

## Known risk

The vehicle stage proves a car showing that plate text was photographed. It does not prove the car or the plate belongs to the driver. Make, model and year are stored but not checked.
