# Model facts

Measured on 2026-11-11 by `scripts/measure_models.py` (CPU provider, intra 2, inter 1, arena off, Windows). Only model facts live here. Hashes are locked in `backend/models/models.lock`. The registry refuses to load on a mismatch.

Locked: YuNet, w600k_r50, YOLO plate detector, `cct_xs_v2_global.onnx` (plate OCR). `genderage.onnx` and `mivolo_v2_age.onnx` are measured only. Age estimation is dropped, they are not locked and the registry never loads them.

## Measured table

<!-- facts:start -->

| File | SHA-256 | Inputs (name, shape, dtype) | Outputs (name, shape, dtype) | Output shape on test run | RSS before -> after (MB) | Latency 5 runs, ms (min / median) | Status |
|---|---|---|---|---|---|---|---|
| cct_xs_v2_global.onnx | `8031afb5fdc6b4d80462c9d542f1284ebd2cfddf5dbacd62609848d7e2855f44` | [('input', ['unk__801', 64, 128, 3], 'tensor(uint8)')] | [('plate', ['unk__802', 10, 37], 'tensor(float)'), ('region', ['unk__803', 66], 'tensor(float)')] | [[1, 10, 37], [1, 66]] | 60 -> 74 | 7.2 / 7.8 | locked |
| face_detection_yunet_2023mar.onnx | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` | [('input', [1, 3, 640, 640], 'tensor(float)')] | [('cls_8', [1, 6400, 1], 'tensor(float)'), ('cls_16', [1, 1600, 1], 'tensor(float)'), ('cls_32', [1, 400, 1], 'tensor(float)'), ('obj_8', [1, 6400, 1], 'tensor(float)'), ('obj_16', [1, 1600, 1], 'tensor(float)'), ('obj_32', [1, 400, 1], 'tensor(float)'), ('bbox_8', [1, 6400, 4], 'tensor(float)'), ('bbox_16', [1, 1600, 4], 'tensor(float)'), ('bbox_32', [1, 400, 4], 'tensor(float)'), ('kps_8', [1, 6400, 10], 'tensor(float)'), ('kps_16', [1, 1600, 10], 'tensor(float)'), ('kps_32', [1, 400, 10], 'tensor(float)')] | [[1, 6400, 1], [1, 1600, 1], [1, 400, 1], [1, 6400, 1], [1, 1600, 1], [1, 400, 1], [1, 6400, 4], [1, 1600, 4], [1, 400, 4], [1, 6400, 10], [1, 1600, 10], [1, 400, 10]] | 69 -> 70 | 28.7 / 30.0 | locked |
| genderage.onnx | `4fde69b1c810857b88c64a335084f1c3fe8f01246c9a191b48c7bb756d6652fb` | [('data', ['None', 3, 96, 96], 'tensor(float)')] | [('fc1', [1, 3], 'tensor(float)')] | [[1, 3]] | 70 -> 71 | 1.7 / 2.0 | unused (age estimation dropped) |
| mivolo_v2_age.onnx | `2db5e05be33b3f120518a86f29a4a65eb0a01c2967219b8787a7dead9b796951` | [('faces_bodies', [1, 6, 384, 384], 'tensor(float)')] | [('age', [1, 1], 'tensor(float)')] | [[1, 1]] | 70 -> 190 | 1263.0 / 1370.8 | unused (age estimation dropped) |
| w600k_r50.onnx | `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43` | [('input.1', ['None', 3, 112, 112], 'tensor(float)')] | [('683', [1, 512], 'tensor(float)')] | [[1, 512]] | 70 -> 237 | 251.4 / 302.3 | locked |
| yolo-v9-t-384-license-plates-end2end.onnx | `888397b96d761c89db40bc9c305838e8652660f5e282c2cadebbe8d2951a77a8` | [('images', [1, 3, 384, 384], 'tensor(float)')] | [('output0', ['batch', 7], 'tensor(float)')] | [[1, 7]] | 70 -> 85 | 84.3 / 88.6 | locked |

<!-- facts:end -->

RSS is process RSS, so "before" includes the Python/ORT baseline. The Windows numbers do not transfer to Linux. Latency uses zero input. Dynamic dims: OCR width 320, YOLO 384, batch 1.

## YuNet (face_detection_yunet_2023mar.onnx)

Fixed input `[1,3,640,640]`. Outputs are 12 tensors in 3 strides (8, 16, 32): `cls_*`, `obj_*`, `bbox_*`, `kps_*` with 6400, 1600, 400 anchors (bbox 4, kps 10 = 5 points x,y). The plan loads it with OpenCV `FaceDetectorYN`, which handles decode. The registry only exposes the path.

## w600k_r50.onnx (face embedder)

Input `input.1` `[N,3,112,112]` float32. Output `683` `[N,512]`. Preprocessing is not verified by this task (ArcFace convention assumed: RGB, (x-127.5)/127.5).

## YOLO plate detector (yolo-v9-t-384-license-plates-end2end.onnx)

- Input `images` `[1,3,384,384]` float32. No ONNX metadata describes preprocessing. Used: letterbox to 384 with pad value 114, RGB, `/255`, NCHW. The detector found the plate with this convention (see fixture below), so it is consistent.
- Output `output0` shape `[N,7]`, N dynamic (NMS is inside the graph, "end2end"). Zero input gave N=1.
- Column layout, inferred from shape and values (no metadata): `[batch_idx, x1, y1, x2, y2, class_id, score]`. Box coordinates are pixels in the 384x384 letterboxed image. Confidence: high. Column 0 is 0.0, columns 1-4 satisfy x2>x1 and y2>y1, column 5 is 0.0 (single class), column 6 is in [0,1]. The decoded box matched the known drawn plate within about 3 px.
- Original-image box: `x = (x_lb - pad_x) / scale`, `y = (y_lb - pad_y) / scale`, `scale = min(384/w, 384/h)`, pad = `((384 - round(w*scale)) // 2, (384 - round(h*scale)) // 2)`.
- Low-score rows are kept in the output (one run returned a 0.67 row and a 0.04 row). The caller must threshold on column 6.

### Fixture

`tests/fixtures/yolo_output.npy`, `yolo_output.json` and `synthetic_vehicle.png` come from a synthetic scene, because no vehicle photo exists. The scene is a grey 1280x720 image, a car-coloured rectangle and a white 300x100 plate at (490,440) with black `ABC123`. The detector found the plate (score 0.67). JSON holds `{"scale": 0.3, "pad": [0, 84], "box": [488.9, 440.8, 790.4, 536.8]}`. The box is the decoded detection, not hand-written. The drawn plate is x 490-790, y 440-540. The detected box ends 3 px high. Task 14 should replace this fixture with a real vehicle photo when one arrives.

## OCR (cct_xs_v2_global.onnx, cct-xs-v2-global-model)

- SHA-256 `8031afb5fdc6b4d80462c9d542f1284ebd2cfddf5dbacd62609848d7e2855f44`, 3,344,292 bytes, matches the model card. About 7 ms per run and +14 MB RSS on this machine.
- Input `input` `[N,64,128,3]` **uint8** NHWC, RGB, 0-255. Output `plate` `[N,10,37]` float and `region` `[N,66]` float. Both are softmax: every plate slot and the region vector sum to 1 (measured).
- Alphabet (37): `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_`. `_` (index 36) is an empty slot. Slot *i* predicts character *i*; there is no CTC and no blank.
- Measured on nine internet photos of Canadian plates: 9 of 9 read exactly, lowest slot probability 0.99 or better. Preprocessing checked two ways (plain resize and aspect-keeping resize): both read all nine.
- Retired: `plate_ocr_ppocrv5_mobile.onnx` + `plate_ocr_dict.json` (18,385-class CTC model), moved to `temp/models/ppocrv5-retired/`.

## Unused models

`genderage.onnx` input `data` `[None,3,96,96]`, output `fc1` `[1,3]`. `mivolo_v2_age.onnx` input `faces_bodies` `[1,6,384,384]`, output `age` `[1,1]`, about 120 MB RSS and 720-760 ms per run. Both are unused.
