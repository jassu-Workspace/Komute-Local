# Stage 3: Vehicle plate and colour

Code: `backend/core/stages/vehicle.py`, `backend/core/matching.py`. Runs only when Stage 1 passed.

## Plate detection

YOLOv9-tiny at 384×384. Preprocessing: letterbox (pad value 114), RGB, `/255`, NCHW. The graph includes NMS, so the output rows are `[batch, x1, y1, x2, y2, class, score]` in letterboxed pixels (inferred and checked; see `docs/MODEL_FACTS.md`). Rows below score 0.35 are dropped, the best box is clipped to the image, and the crop gets an 8% margin. No plate gives `PLATE_NOT_FOUND` (retryable).

## Plate reading

PP-OCRv5 mobile with `plate_ocr_dict.json`. The model has **18,385 classes** (blank, 18,383 dictionary characters, space), most of them CJK. It is not a 36-class model. The crop is resized to 48 px high (width 48–320, aspect kept) and normalised to `(x/255 − 0.5)/0.5`.

Decoding is greedy CTC with a plate-only rule: the model's own argmax decides blank or character at each step. At a character step the best allowed class (`A–Z`, `0–9`) is taken, so a CJK or symbol class never reaches the output. Repeats collapse, and a blank separates a real double letter. The confidence is the mean probability of the chosen characters.

An empty read or a confidence below 0.6 gives `PLATE_UNREADABLE` (retryable), not a mismatch.

## Plate rule

After removing everything but `A–Z` and `0–9`, the read matches the claimed plate if the strings are equal, or if they have equal length and differ in exactly one position and that pair is `O/0`, `I/1` or `B/8`. Anything else gives `PLATE_MISMATCH` (final).

## Colour (advisory only)

Four patches next to the plate (above, below, left, right) are converted to CIELAB. Pixels with L\* between 5 and 99 are kept, K-means (K = 3, fixed seed) finds the dominant cluster, and the nearest of 14 reference colours (CIE76) is the result. The spec's L\* > 92 glare cutoff was changed to 99, because the spec's own white reference is L\* 96 and white cars would have been discarded.

A mismatch adds advisory `COLOUR_MISMATCH`. An unknown claimed colour or too few pixels adds `COLOUR_UNVERIFIED`. Colour never blocks approval.

## Known risk

The vehicle stage proves a car showing that plate text was photographed. It does not prove the car or the plate belongs to the driver. Make, model and year are stored but not checked.
