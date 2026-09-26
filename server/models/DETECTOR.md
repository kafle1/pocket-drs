# Ball detector data card

`cricket_ball.pt` is the learned ball detector that `app/pipeline/process_job.py` loads (`YOLO_WEIGHTS`).
It is YOLOv8n fine-tuned to a single class, `ball`. Rebuild it with one command:

    server/.venv/bin/python server/scripts/train_ball_detector.py --clips <folder with test3/4/5.mp4> \
        --roboflow <folder with the two Roboflow zips>

The photos download on their own. The two Roboflow zips must be fetched by hand first (see Video frames).
`--roboflow` defaults to `../pocket-drs-data/downloads` next to the repo. Git ignores `**/models/*.pt`,
so check any copy of the weights against the hash below.

## Weights

| File | SHA-256 |
|---|---|
| `cricket_ball.pt` | `bb5e633409dfb5b2d364a57c3b2a5e4c24804ae7110a46046efd228053f1fb97` |
| base `yolov8n.pt`, ultralytics/assets release v8.3.0 | `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36` |
| `detector_manifest.csv` (every image used) | `7f43a873b80d822236fe0d7ecd793e64b09c0b04bbea3f23c7c18d4ffdfe2f2c` |
| `cricket-ball-cricv2-v2.yolov8.zip` | `cf5b639049163af467ee8fb80369698d4a9dd64b880e83ad5ed8633cfa3dd1d2` |
| `cricket-ball-tracker-v1.yolov5.zip` | `02547bae5ccb073a36d5884ad63c62297cab52e8491c76a43f5ba0b08c49f45e` |

The base weights are the COCO-pretrained YOLOv8n published by Ultralytics under AGPL-3.0.
Trained with ultralytics 8.4.52 and torch 2.12 on Apple MPS.

## Credits

The cricket video frames come from two datasets on Roboflow Universe, both under CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). The frames were filtered, deduplicated, turned back upright,
resized to their original frame shape and relabelled to one class, as described below.

- "Cricket Ball - v2 CricV2" by cricket-ball-zgk1s, Roboflow Universe,
  https://universe.roboflow.com/cricket-ball-zgk1s/cricket-ball-qwzrd/dataset/2, CC BY 4.0.
- "cricket ball tracker - v1" (2023-03-25 6:50pm) by uopcrictrakcr, Roboflow Universe,
  https://universe.roboflow.com/uopcrictrakcr/cricket-ball-tracker/dataset/1, CC BY 4.0.

## Data

| Source | Images train / val | Boxes train / val | Licence |
|---|---|---|---|
| Open Images V7, Cricket ball (`/m/02ctlc`) | 86 / 15 | 106 / 15 | boxes CC BY 4.0 (Google); images listed as CC BY 2.0 |
| Open Images V7, Tennis ball (`/m/05ctyq`) | 339 / 60 | 408 / 73 | same |
| COCO 2017, sports ball (category 37) | 837 / 148 | 1,122 / 223 | annotations CC BY 4.0; images CC BY 2.0 (648), CC BY-SA 2.0 (328), no known copyright restrictions (9) |
| Roboflow, cricket ball tracker v1 (video frames) | 1,771 / 306 | 1,783 / 312 | CC BY 4.0 |
| Roboflow, CricV2 v2 (video frames) | 121 / 52 | 121 / 52 | CC BY 4.0 |
| Total | 3,154 / 581 | 3,540 / 675 | |

Photo validation (223 images) and video validation (358 frames) are kept apart and scored apart.
`detector_manifest.csv` gives each image's URL or zip member, origin, licence and author.

### Photos

- Open Images boxes: `https://storage.googleapis.com/openimages/v5/validation-annotations-bbox.csv`,
  `v5/test-annotations-bbox.csv`, `v6/oidv6-train-annotations-bbox.csv`; image licences and rotation from
  `2018_04/*-with-rotation.csv`; pictures from `https://open-images-dataset.s3.amazonaws.com/`.
- COCO: `http://images.cocodataset.org/annotations/annotations_trainval2017.zip`; pictures from `images.cocodataset.org`.
- Open Images: images with at least one Cricket ball or Tennis ball box. A generic Ball box is kept only inside
  those images, and merged with any ball box it overlaps at IoU 0.7 or more. An image is dropped if any ball box
  is a group box or a drawing, or if the original is rotated.
- COCO: sports-ball images with one of the licences above and no crowd box. Non-commercial and
  no-derivatives images (COCO licences 1, 2, 3, 6) are left out.
- A Flickr photo found in both sets is kept once. Images with an EXIF orientation other than 1 are dropped.
- Split: 15% of each source held out, from a `numpy.random.default_rng(0)` permutation of sorted names.
  This is the same photo split as the earlier photo-only detector.
- Each training photo also gets a motion-blurred twin. Each ball is smeared along a random straight line
  1 to 4 ball widths long (3 to 80 px) over the sharp background, and its box is stretched to the streak.
- Cricket-ball photos and their twins are listed 4 times, because only 101 true cricket-ball photos exist.

### Video frames

Both zips are read as downloaded, without unpacking. Every box in a kept frame becomes `ball`
(set 2 labels balls under two class names). Frames with several boxes are kept.

Set 1, CricV2 (5,886 images in the zip). Only phone and net-camera frames are kept. Left out by file name:

| Group | Images | Why |
|---|---|---|
| `img#_jpg` | 996 | TV broadcast (Sky Sports graphics) |
| `Screenshot-from-*` | 437 | TV broadcast (ECB graphics) |
| `frame#_jpg` | 159 | TV broadcast (TEAM NATION graphics) |
| `istockphoto-*` | 83 | stock photos |
| web product shots (`kookaburra-*`, `images#_jpeg`, `maxresdefault` and others) | 33 | not video, watermarked or cut out |

Its training split was exported twice per image with a random quarter turn, brightness change and blur.
Each training copy is turned back by matching a 32x32 blurred thumbnail against the unaugmented frames under
0, 90 and 270 degree turns. A turn is accepted at correlation 0.85 or more and at least 0.05 above the next
turn. The boxes are turned with the image. 242 copies had no clear match and were dropped.

Set 2, cricket ball tracker (9,718 images in the zip). Left out:
- 874 images (544 source frames) whose file name contains `Y2Mate` in any case, which marks a YouTube download.
- 715 four-tile mosaic exports in the `frame#_jpg` group. Tiles meet on one full-width row and one
  full-height column, where nearly every pixel steps in brightness. For each row boundary the 20th percentile
  of the step is taken; a frame is a mosaic when the strongest row scores at least 2.5 times the median row
  (plus 0.5 grey levels), and the strongest column does too. Plain frames score up to about 2.
  The README says no augmentation was applied, but these tiles show salt-and-pepper noise and cut-up frames.

Near copies. Both sets are exported as 640x640 frames from video, so neighbouring frames repeat.
12,065 candidates were reduced to 2,250 by a greedy pass that drops any frame within 4 of 64 bits of an earlier
kept frame (DCT perceptual hash). Set 2 frames, originals and frames with a ball come first.
9,815 near copies were dropped.

Scenes and split. Frames are grouped into scenes: connected groups of frames whose 32x32 thumbnails
correlate at 0.85 or more (built before the copy pass, so a dropped copy still links its neighbours).
This gives 100 scenes, the largest holding 596, 397, 211, 113 and 108 frames. Scenes are taken in a
`numpy.random.default_rng(0)` order into validation, skipping any scene that would push validation past 20%,
until validation holds at least 15%. Result: 24 scenes, 358 frames (15.9%), in validation.
The closest validation frame to any training frame, mirrors included, has 64x64 thumbnail correlation 0.794.

Frame shape. Both sets squash each frame to a square, so a round ball gets a box whose width over height
equals the true frame's height over width. In a scene with at least 10 boxes of 10 px or more, the median of
that ratio is matched to 16:9, 4:3, 1:1, 3:4 or 9:16 within 12%. Frames of a matched scene are resized back
to that shape with a 640 px long side: 739 to 9:16 portrait, 596 to 3:4 portrait, 77 to 16:9 and 25 to 4:3.
81 are in square scenes. 732 stay as exported because their scene gave no clear answer.

Caps. At most 10% of the video training frames may have no ball; there is 1. No video source may pass 40%
of the training list; neither does, so nothing was thinned.

Training list: 4,932 entries. Share by source:

| Source | Share |
|---|---|
| Roboflow cricket ball tracker | 35.9% |
| COCO sports ball (with twins) | 33.9% |
| Open Images cricket ball (with twins, 4 times) | 13.9% |
| Open Images tennis ball (with twins) | 13.7% |
| Roboflow CricV2 | 2.5% |

## Leakage check

No frame rendered by `paper/experiments/render.py`, nothing from the Exp 2 grid, and no frame of the
Exp 3 clips (test3, test4, test5) is in the data.

This was checked by content. All 4,997 dataset images (1,262 training photos, 1,262 blurred twins, 223 photo
validation images, 1,892 video training frames and 358 video validation frames), each also mirrored, were
compared with every readable frame of test3, test4 and test5 (296 frames) and every frame of three render.py
clips from the grid (deliveries 0, 37 and 74, 183 frames), using a 64-bit DCT perceptual hash.
A pair counts as a duplicate at Hamming distance 10 or less and 64x64 thumbnail correlation 0.9 or more.

Result: 0 duplicates. The closest pair is 14 bits apart out of 64. The script refuses to train if any
duplicate is found.

## Training

YOLOv8n, image size 640, batch 8, 40 epochs with patience 15, optimizer `auto`, lr0 0.01, seed 0,
deterministic, single class, scale 0.9, mosaic 1.0 (off for the last 10 epochs), horizontal flip 0.5,
translate 0.1, AMP, 1 data worker. Disk cache was on: the script measured it at 4.6 GB with 50.9 GB free,
under its 15 GB limit. `best.pt` (by 0.1 mAP50 + 0.9 mAP50-95) is chosen on both validation sets together.
Reruns on MPS are close but not bit-exact.

The 40 epochs took 4.1 hours while other jobs loaded the machine. The best epoch was the last one (40),
so the score was still rising and a longer run may do better.

## Validation

Confidence and IoU at Ultralytics validation defaults.

| Validation set | Image size | Precision | Recall | mAP50 | mAP50-95 |
|---|---|---|---|---|---|
| Photos, 223 images, 311 boxes | 640 | 0.789 | 0.627 | 0.684 | 0.434 |
| Photos | 1280 (the pipeline's size) | 0.724 | 0.684 | 0.681 | 0.431 |
| Video frames, 358 frames, 364 boxes | 640 | 0.798 | 0.411 | 0.483 | 0.266 |
| Video frames | 1280 | 0.501 | 0.481 | 0.402 | 0.232 |

The earlier photo-only detector (SHA-256 `d4401a92...`) on the same sets: photos 0.686 mAP50 at 640 and
0.669 at 1280, video frames 0.181 at 640 and 0.040 at 1280. Adding the video frames left the photo score
where it was and lifted the video score.

At the pipeline's own setting (1280 px, confidence 0.2), a box counts as found at IoU 0.5 or more:

| Val subset | Boxes | Found | Recall | Detections | Precision |
|---|---|---|---|---|---|
| All photos | 311 | 228 | 0.73 | 370 | 0.62 |
| Open Images cricket ball | 15 | 13 | 0.87 | 23 | 0.57 |
| Open Images tennis ball | 73 | 69 | 0.95 | 121 | 0.57 |
| COCO sports ball | 223 | 146 | 0.65 | 226 | 0.65 |
| All video frames | 364 | 197 | 0.54 | 483 | 0.41 |
| Roboflow cricket ball tracker | 312 | 156 | 0.50 | 410 | 0.38 |
| Roboflow CricV2 | 52 | 41 | 0.79 | 73 | 0.56 |

The photo-only detector at the same setting found 0.75 of the photo boxes but only 0.20 of the video boxes
(73 of 364, precision 0.12).

Neither photo source promises to box every ball, so some of the false detections may be real, unboxed balls.
The cricket-ball photo row rests on 15 boxes and is only a rough guide. The video rows come from 24 scenes,
so they move with a few hard scenes.

## Limits

- The video frames are other people's footage from the two Roboflow sets, not nets filmed with this app.
  The video scores describe footage like theirs, not the app's own clips.
- The only test on the app's own footage is Exp 3, three clips kept out of training (see Leakage check).
  On the current code, the analyses out of 9 that returned a verdict instead of discarding the track:
  9 with these weights, 8 with the photo-only retrain, 7 with the colour tracker alone, and 6 in the
  submitted run.
- On the rendered grid (Exp 2) these weights give 96/100 correct, 0 false outs and 0 missed outs.
- Open Images publishes its image licences as "listed as" CC BY 2.0, without warranty.
  CC BY-SA 2.0 photos are in the training set.
- The Roboflow uploaders licence their sets as CC BY 4.0. The frames left in are phone and net-camera
  footage, but their original owners cannot be checked from the zips.
- The base weights were trained by Ultralytics on all of COCO, including non-commercial images.
- Ultralytics treats fine-tuned weights as covered by AGPL-3.0. Publishing them next to closed code needs
  AGPL terms for the weights or an Ultralytics licence.

## Sources not used

- Parts of both Roboflow sets, listed under Video frames: TV broadcast frames, stock photos, web product
  shots, YouTube downloads and mosaic exports.
- `Ranvin36/cricket-synth` (Hugging Face, MIT): rendered in Blender, so it would break the rule that the
  detector never sees rendered frames.
- `louis392/Cricket-Dataset` (Hugging Face): gated behind an account.
- `infactory-ai/ball-tracking` (Hugging Face): CC BY-NC 4.0 and soccer footage.
- `arunabh-ramesh/cricket-vision-dataset` (no licence stated) and `GobbleGobbleGobble/suksham-cricket-frames`
  (scene labels, no ball boxes).
- Kaggle cricket-ball sets need an account.
