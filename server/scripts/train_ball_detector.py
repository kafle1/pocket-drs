#!/usr/bin/env python
"""Rebuild server/models/cricket_ball.pt, the learned ball detector, from public data in one command.

Usage:  server/.venv/bin/python server/scripts/train_ball_detector.py [--work DIR] [--clips DIR]
            [--roboflow DIR] [--model yolov8n.pt] [--epochs 40] [--batch 8] [--device mps] [--no-train]

Photo sources download without an account:
  Open Images V7 boxes for Cricket ball and Tennis ball (boxes CC BY 4.0, images listed as CC BY 2.0).
  COCO 2017 sports ball boxes (CC BY 4.0), only images whose Flickr licence is CC BY, CC BY-SA,
  no known copyright restrictions or US Government work.
Cricket video frames come from two Roboflow Universe exports (both CC BY 4.0) that must already sit in
--roboflow: cricket-ball-cricv2-v2.yolov8.zip and cricket-ball-tracker-v1.yolov5.zip. They are read
straight from the zips, cleaned (see load_video), split by scene, and held out as a second validation set.
All ball boxes in a kept image become one class. Training photos also get a motion-blurred twin in
which each ball is smeared along a random line over a sharp background. No rendered frame and no
frame of the Exp 3 clips is used, and before training every image is compared by perceptual hash
with every frame of test3/test4/test5 and with frames from paper/experiments/render.py; the run
stops on any near duplicate. See server/models/DETECTOR.md for the resulting data card.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy.fft import dct
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

ROOT = Path(__file__).resolve().parents[2]
OI = "https://storage.googleapis.com/openimages/"
OI_BOXES = {"validation": "v5/validation-annotations-bbox.csv", "test": "v5/test-annotations-bbox.csv",
            "train": "v6/oidv6-train-annotations-bbox.csv"}
OI_META = {"validation": "2018_04/validation/validation-images-with-rotation.csv",
           "test": "2018_04/test/test-images-with-rotation.csv",
           "train": "2018_04/train/train-images-boxable-with-rotation.csv"}
OI_IMG = "https://open-images-dataset.s3.amazonaws.com/{split}/{id}.jpg"
OI_BALLS = {"/m/02ctlc": "cricket", "/m/05ctyq": "tennis", "/m/018xm": "ball"}
OI_SELECT = ("cricket", "tennis")                  # generic Ball boxes are kept only inside these images
COCO_ZIP = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
COCO_BALL = 37                                     # sports ball
COCO_LICENCES = {4: "CC BY 2.0", 5: "CC BY-SA 2.0", 7: "No known copyright restrictions", 8: "US Government work"}
BASE_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/{}"
SEED = 0
VAL_FRAC = 0.15
CRICKET_REPEAT = 4                                 # the only true cricket-ball source is small
HASH_DIST = 10                                     # of 64 bits; a candidate must also pass the thumbnail check
THUMB_CORR = 0.9
POPCOUNT = np.array([bin(i).count("1") for i in range(256)], np.uint8)

RF_SETS = {
    "s1": dict(zip="cricket-ball-cricv2-v2.yolov8.zip", source="roboflow_cricv2", author="cricket-ball-zgk1s",
               origin="https://universe.roboflow.com/cricket-ball-zgk1s/cricket-ball-qwzrd/dataset/2"),
    "s2": dict(zip="cricket-ball-tracker-v1.yolov5.zip", source="roboflow_tracker", author="uopcrictrakcr",
               origin="https://universe.roboflow.com/uopcrictrakcr/cricket-ball-tracker/dataset/1"),
}
S1_KEEP = re.compile(r"^(\d+_jpg|\d+-\d+-_jpg|img_\d+_JPG)\.rf\.")   # the rest is TV broadcast, stock or product shots
S2_MOSAIC_GROUP = re.compile(r"^frame\d+_jpg\.rf\.")             # the only group holding 4-tile mosaic exports
MOSAIC_SCORE = 2.5                                  # plain frames score up to about 2, mosaics 3 and up
ORIENT_CORR, ORIENT_MARGIN = 0.85, 0.05
DUP_BITS = 4
SCENE_CORR = 0.85
SOURCE_CAP = 0.4                                    # of all training entries, per video source
MAX_BACKGROUND = 0.1
FRAME_HW = np.array([16 / 9, 4 / 3, 1.0, 3 / 4, 9 / 16])   # standard frame height / width
MANIFEST = ["name", "source", "split", "boxes", "width", "height", "url", "origin", "licence", "author",
            "scene", "rotated", "frame_hw"]

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = None


def fetch(url: str, dest: Path) -> Path:
    if not dest.exists():
        tmp = dest.with_name(dest.name + ".part")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=60, context=CTX) as r, open(tmp, "wb") as fh:
                    shutil.copyfileobj(r, fh, 1 << 20)
                break
            except OSError:
                if attempt == 2:
                    raise
        tmp.rename(dest)
    return dest


def stream_filter(url: str, dest: Path, keep, prefix: str = "") -> None:
    """Append the lines of a large remote CSV that keep() accepts, without storing the whole file."""
    with urllib.request.urlopen(url, timeout=60, context=CTX) as r, open(dest, "a") as out:
        for raw in r:
            line = raw.decode("utf-8").rstrip("\n")
            if keep(line):
                out.write(prefix + line + "\n")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def open_images(work: Path) -> list[dict]:
    """Kept Open Images pictures with normalised x0,y0,x1,y1 boxes, licence and author."""
    boxes = work / "oi_boxes.csv"
    if not boxes.exists():
        tmp = boxes.with_name("oi_boxes.part")
        tmp.unlink(missing_ok=True)
        for split, rel in OI_BOXES.items():
            stream_filter(OI + rel, tmp, lambda l: l.split(",", 3)[2] in OI_BALLS if l.count(",") > 3 else False,
                          prefix=split + ",")
        tmp.rename(boxes)
    per = defaultdict(list)
    with open(boxes) as fh:
        for split, iid, _src, label, _conf, x0, x1, y0, y1, _occ, _trunc, group, depic, *_ in csv.reader(fh):
            per[(split, iid)].append((OI_BALLS[label], float(x0), float(y0), float(x1), float(y1), group == "1" or depic == "1"))
    chosen = {k: v for k, v in per.items()
              if any(b[0] in OI_SELECT for b in v) and not any(b[5] for b in v)}   # group or drawing boxes spoil an image
    meta_path = work / "oi_meta.csv"
    if not meta_path.exists():
        ids = {iid for _, iid in chosen}
        tmp = meta_path.with_name("oi_meta.part")
        tmp.unlink(missing_ok=True)
        for rel in OI_META.values():
            stream_filter(OI + rel, tmp, lambda l: l.split(",", 1)[0] in ids)
        tmp.rename(meta_path)
    meta = {}
    with open(meta_path) as fh:
        for row in csv.reader(fh):
            iid, _subset, url, _landing, licence, _prof, author, *_mid, rotation = row
            meta[iid] = dict(url=url, licence=licence, author=author, rotation=rotation)
    out = []
    for (split, iid), bs in sorted(chosen.items()):
        m = meta.get(iid)
        if m is None or m["rotation"] not in ("", "0", "0.0"):
            continue                                  # a rotated original would not match its boxes
        order = sorted(bs, key=lambda b: b[0] == "ball")
        kept = []
        for b in order:
            if all(iou(b[1:5], k[1:5]) < 0.7 for k in kept):
                kept.append(b)                         # a Tennis ball is often boxed again as Ball
        kind = "cricket" if any(b[0] == "cricket" for b in kept) else "tennis"
        out.append(dict(name=f"oi_{iid}", source=f"openimages_{kind}", url=OI_IMG.format(split=split, id=iid),
                        origin=m["url"], licence="CC BY 2.0" if "by/2.0" in m["licence"] else m["licence"],
                        author=m["author"], boxes=[b[1:5] for b in kept], norm=True))
    return out


def coco(work: Path) -> list[dict]:
    """Kept COCO 2017 pictures with pixel x0,y0,x1,y1 boxes, licence restricted to redistributable ones."""
    ann_dir = work / "coco"
    if not (ann_dir / "annotations" / "instances_val2017.json").exists():
        z = fetch(COCO_ZIP, work / "coco_annotations.zip")
        with zipfile.ZipFile(z) as zf:
            for part in ("instances_train2017.json", "instances_val2017.json"):
                zf.extract("annotations/" + part, ann_dir)
    out = []
    for part in ("train2017", "val2017"):
        d = json.loads((ann_dir / "annotations" / f"instances_{part}.json").read_text())
        balls = defaultdict(list)
        for a in d["annotations"]:
            if a["category_id"] == COCO_BALL:
                balls[a["image_id"]].append(a)
        for im in d["images"]:
            anns = balls.get(im["id"])
            if not anns or im["license"] not in COCO_LICENCES or any(a["iscrowd"] for a in anns):
                continue
            bs = [(a["bbox"][0], a["bbox"][1], a["bbox"][0] + a["bbox"][2], a["bbox"][1] + a["bbox"][3]) for a in anns]
            out.append(dict(name=f"coco_{im['id']:012d}", source="coco_sports_ball", url=im["coco_url"],
                            origin=im["flickr_url"], licence=COCO_LICENCES[im["license"]], author="",
                            boxes=bs, norm=False))
        del d
    return sorted(out, key=lambda r: r["name"])


def flickr_id(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("_", 1)[0]


def dedupe(items: list[dict]) -> list[dict]:
    """COCO and Open Images both come from Flickr; keep one copy of a photo so it cannot sit in both splits."""
    seen, out = set(), []
    for it in items:
        key = flickr_id(it["origin"])
        if key and key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def download(items: list[dict], raw: Path) -> list[dict]:
    raw.mkdir(parents=True, exist_ok=True)

    def one(it):
        try:
            fetch(it["url"], raw / f"{it['name']}.jpg")
            return it
        except OSError:
            return None

    with ThreadPoolExecutor(16) as pool:
        got = [it for it in pool.map(one, items) if it is not None]
    print(f"  downloaded {len(got)}/{len(items)} images")
    return got


def yolo_lines(boxes, w: int, h: int, norm: bool) -> list[str]:
    lines = []
    for x0, y0, x1, y1 in boxes:
        if not norm:
            x0, x1, y0, y1 = x0 / w, x1 / w, y0 / h, y1 / h
        x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1)
        if x1 - x0 > 1e-4 and y1 - y0 > 1e-4:
            lines.append(f"0 {(x0 + x1) / 2:.6f} {(y0 + y1) / 2:.6f} {x1 - x0:.6f} {y1 - y0:.6f}")
    return lines


def motion_blur(img: np.ndarray, lines: list[str], rng) -> tuple[np.ndarray, list[str]]:
    """Smear each ball along a random line over a sharp background, and stretch its box to the streak."""
    h, w = img.shape[:2]
    out = img.astype(np.float32)
    new = []
    for ln in lines:
        _, cx, cy, bw, bh = map(float, ln.split())
        size = max(bw * w, bh * h)
        length = int(np.clip(rng.uniform(1.0, 4.0) * size, 3, 80))
        theta = rng.uniform(0, np.pi)
        k = np.zeros((length, length), np.float32)
        c = (length - 1) / 2
        dx, dy = np.cos(theta) * c, np.sin(theta) * c
        cv2.line(k, (int(round(c - dx)), int(round(c - dy))), (int(round(c + dx)), int(round(c + dy))), 1.0, 1)
        k /= k.sum()
        pad = length
        x0, x1 = max(0, int((cx - bw / 2) * w) - pad), min(w, int((cx + bw / 2) * w) + pad + 1)
        y0, y1 = max(0, int((cy - bh / 2) * h) - pad), min(h, int((cy + bh / 2) * h) + pad + 1)
        patch = out[y0:y1, x0:x1]
        mask = np.zeros(patch.shape[:2], np.float32)
        cv2.ellipse(mask, (int(cx * w) - x0, int(cy * h) - y0), (max(1, int(bw * w / 2)), max(1, int(bh * h / 2))),
                    0, 0, 360, 1.0, -1)
        alpha = cv2.filter2D(mask, -1, k)[..., None]
        smear = cv2.filter2D(patch * mask[..., None], -1, k)
        out[y0:y1, x0:x1] = smear + (1 - alpha) * patch
        nbw = min(1.0, bw + abs(np.cos(theta)) * (length - 1) / w)
        nbh = min(1.0, bh + abs(np.sin(theta)) * (length - 1) / h)
        new.append(f"0 {cx:.6f} {cy:.6f} {nbw:.6f} {nbh:.6f}")
    return np.clip(out, 0, 255).astype(np.uint8), new


def desc32(ths) -> np.ndarray:
    """Blurred 32x32 grey thumbnails as zero-mean unit rows, for scene and orientation matching."""
    t = np.stack([cv2.resize(cv2.GaussianBlur(t, (5, 5), 0), (32, 32), interpolation=cv2.INTER_AREA) for t in ths])
    t = t.reshape(len(t), -1).astype(np.float32)
    t -= t.mean(1, keepdims=True)
    return t / (np.linalg.norm(t, axis=1, keepdims=True) + 1e-6)


def mosaic_score(g: np.ndarray) -> float:
    """Roboflow mosaic tiles meet on one full-width row and one full-height column; score the weaker seam."""
    g = cv2.GaussianBlur(g, (3, 3), 0).astype(np.float32)
    r = np.percentile(np.abs(np.diff(g, axis=0)), 20, axis=1)
    c = np.percentile(np.abs(np.diff(g, axis=1)), 20, axis=0)
    return float(min(r.max() / (np.median(r) + 0.5), c.max() / (np.median(c) + 0.5)))


def rf_boxes(text: str) -> list[tuple]:
    """Normalised cx,cy,w,h for every labelled object; every class is a ball."""
    out = []
    for ln in text.splitlines():
        try:
            v = [float(x) for x in ln.split()[1:]]
        except ValueError:
            continue
        if len(v) == 4:
            x0, y0, x1, y1 = v[0] - v[2] / 2, v[1] - v[3] / 2, v[0] + v[2] / 2, v[1] + v[3] / 2
        elif len(v) >= 6 and len(v) % 2 == 0:
            x0, x1, y0, y1 = min(v[0::2]), max(v[0::2]), min(v[1::2]), max(v[1::2])
        else:
            continue
        x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1)
        if x1 - x0 > 1e-4 and y1 - y0 > 1e-4:
            out.append(((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0))
    return out


def rot_boxes(boxes, k: int):
    for _ in range(k):                                  # np.rot90 turns counterclockwise
        boxes = [(cy, 1 - cx, h, w) for cx, cy, w, h in boxes]
    return boxes


def components(d: np.ndarray, thr: float) -> np.ndarray:
    """Connected components of the graph joining rows whose dot product reaches thr."""
    r, c = [], []
    for a in range(0, len(d), 2048):
        i, j = np.nonzero(d[a:a + 2048] @ d.T >= thr)
        r.append(i + a)
        c.append(j)
    r, c = np.concatenate(r), np.concatenate(c)
    return connected_components(coo_matrix((np.ones(len(r), bool), (r, c)), shape=(len(d), len(d))), directed=False)[1]


def load_video(rf_dir: Path) -> dict:
    """Candidate frames from both Roboflow zips, cleaned, deduplicated and split by scene.

    Set 1 (cricv2): only the phone and net-camera groups are kept (S1_KEEP). Its training split is exported
    with a random quarter turn, so each training frame is turned back by matching it against unaugmented frames.
    Set 2 (tracker): both classes are balls; Y2Mate downloads and 4-tile mosaic exports are dropped.
    Both sets squash frames to 640x640; each scene gets its frame shape back when its ball boxes agree on one.
    """
    rep = dict(excluded=Counter(), y2mate_stems=0, candidates=Counter())
    cands, y2 = [], set()
    for tag, meta in RF_SETS.items():
        path = rf_dir / meta["zip"]
        if not path.exists():
            sys.exit(f"missing {path}; pass --roboflow with the folder holding both Roboflow zips")
        with zipfile.ZipFile(path) as z:
            members = set(z.namelist())
            for n in sorted(members):
                if "/images/" not in n or n.endswith("/"):
                    continue
                base = n.rsplit("/", 1)[1]
                stem = base.split(".rf.")[0]
                if tag == "s2" and "y2mate" in base.lower():
                    rep["excluded"]["s2 Y2Mate"] += 1
                    y2.add(stem)
                    continue
                if tag == "s1" and not S1_KEEP.match(base):
                    rep["excluded"]["s1 " + re.sub(r"\d+", "#", stem)] += 1
                    continue
                g = cv2.imdecode(np.frombuffer(z.read(n), np.uint8), cv2.IMREAD_GRAYSCALE)
                if g is None:
                    rep["excluded"][f"{tag} unreadable"] += 1
                    continue
                if tag == "s2" and S2_MOSAIC_GROUP.match(base) and mosaic_score(g) >= MOSAIC_SCORE:
                    rep["excluded"]["s2 mosaic"] += 1
                    continue
                lab = n.replace("/images/", "/labels/").rsplit(".", 1)[0] + ".txt"
                split = n.split("/")[0]
                cands.append(dict(set=tag, member=n, name=f"rf_{tag}_{split}_{base.rsplit('.', 1)[0]}",
                                  h=g.shape[0], w=g.shape[1], th=cv2.resize(g, (64, 64), interpolation=cv2.INTER_AREA),
                                  boxes=rf_boxes(z.read(lab).decode()) if lab in members else [], k=0,
                                  aug=tag == "s1" and split == "train"))
    rep["y2mate_stems"] = len(y2)
    if not cands:
        sys.exit("no usable frames in the Roboflow zips")
    rep["candidates"] = Counter(f"{c['set']} {'train copy' if c['aug'] else 'original'}" for c in cands)

    ref = [c for c in cands if not c["aug"]]
    aug = [c for c in cands if c["aug"]]
    kept = list(ref)
    if aug:
        r = desc32([c["th"] for c in ref])
        score = np.stack([(desc32([np.rot90(c["th"], k) for c in aug]) @ r.T).max(1) for k in (0, 1, 3)], 1)
        top = np.sort(score, 1)
        ok = (top[:, -1] >= ORIENT_CORR) & (top[:, -1] - top[:, -2] >= ORIENT_MARGIN)
        for c, s, good in zip(aug, score, ok):
            if not good:
                rep["excluded"]["s1 turn not resolved"] += 1
                continue
            c["k"] = (0, 1, 3)[int(s.argmax())]
            c["th"] = np.ascontiguousarray(np.rot90(c["th"], c["k"]))
            c["boxes"] = rot_boxes(c["boxes"], c["k"])
            if c["k"] % 2:
                c["h"], c["w"] = c["w"], c["h"]
            kept.append(c)
        rep["turned_back"] = Counter(90 * c["k"] for c in kept if c["aug"])

    # scenes come from every surviving candidate, so a frame dropped as a copy still links its neighbours
    for c, lab in zip(kept, components(desc32([c["th"] for c in kept]), SCENE_CORR)):
        c["scene"] = int(lab)
    hashes = np.stack([phash(c["th"]) for c in kept])
    order = sorted(range(len(kept)), key=lambda j: (kept[j]["set"] != "s2", kept[j]["aug"], not kept[j]["boxes"],
                                                    kept[j]["member"]))
    chosen = np.empty(len(kept), int)
    n = 0
    for j in order:
        if n and (POPCOUNT[np.bitwise_xor(hashes[chosen[:n]], hashes[j])].sum(1) <= DUP_BITS).any():
            continue
        chosen[n] = j
        n += 1
    pool = sorted((kept[j] for j in chosen[:n]), key=lambda c: c["member"])
    rep["near_copies_dropped"] = len(kept) - len(pool)

    size = Counter(c["scene"] for c in pool)
    scenes = sorted(size)
    rng = np.random.default_rng(SEED)
    val, n_val = set(), 0
    for s in (scenes[i] for i in rng.permutation(len(scenes))):
        if n_val >= VAL_FRAC * len(pool):
            break
        if n_val + size[s] <= 0.2 * len(pool):
            val.add(s)
            n_val += size[s]
    by_scene = defaultdict(list)
    for c in pool:
        c["split"] = "val_video" if c["scene"] in val else "train"
        by_scene[c["scene"]].append(c)

    for mem in by_scene.values():
        ratios = [w / h for c in mem for _, _, w, h in c["boxes"] if min(w * c["w"], h * c["h"]) >= 10]
        hw = None
        if len(ratios) >= 10:
            m = float(np.median(ratios))
            j = int(np.abs(np.log(FRAME_HW / m)).argmin())
            if abs(np.log(FRAME_HW[j] / m)) <= np.log(1.12):   # ball boxes are round in the true frame shape
                hw = float(FRAME_HW[j])
        for c in mem:
            c["hw"] = hw if c["w"] == c["h"] else None

    tr = [c for c in pool if c["split"] == "train"]
    va = [c for c in pool if c["split"] == "val_video"]
    if tr and va:
        t = np.stack([thumb(c["th"]) for c in tr])
        v = np.stack([thumb(x) for c in va for x in (c["th"], np.ascontiguousarray(c["th"][:, ::-1]))])
        rep["val_train_max_thumb_corr"] = round(float((v @ t.T).max()), 3)
    rep.update(scenes=len(scenes), val_scenes=len(val), pool=Counter(f"{c['set']} {c['split']}" for c in pool),
               frame_shape_restored=Counter(str(round(c["hw"], 3)) for c in pool if c["hw"] not in (None, 1.0)),
               largest_scenes=sorted(size.values(), reverse=True)[:5])
    return dict(pool=pool, report=rep)


def write_video(video: dict, rf_dir: Path, ds: Path, n_photo: int, rows: list[dict]) -> list[str]:
    """Cap each video source and the background frames, then write the frames and their labels."""
    pool, rep = video["pool"], video["report"]
    train = [c for c in pool if c["split"] == "train"]
    drop = {id(c) for c in [c for c in train if not c["boxes"]][int(MAX_BACKGROUND * len(train)):]}
    rep["capped"] = {}
    for tag in RF_SETS:
        mine = [c for c in train if c["set"] == tag and id(c) not in drop]
        others = n_photo + sum(1 for c in train if c["set"] != tag and id(c) not in drop)
        cap = int(SOURCE_CAP / (1 - SOURCE_CAP) * others)
        if len(mine) <= cap:
            continue
        by = defaultdict(list)
        for c in mine:
            by[c["scene"]].append(c)
        # thin the biggest scenes first: every scene keeps at most `top` frames, spread along its names
        top = max(t for t in range(max(map(len, by.values())) + 1) if sum(min(len(v), t) for v in by.values()) <= cap)
        for v in by.values():
            if len(v) > top:
                keep = set(np.linspace(0, len(v) - 1, top).round().astype(int).tolist()) if top else set()
                drop |= {id(c) for i, c in enumerate(v) if i not in keep}
        rep["capped"][tag] = dict(before=len(mine), cap=cap, per_scene_limit=top,
                                  after=sum(1 for c in mine if id(c) not in drop))
    entries, written = [], Counter()
    zips = {tag: zipfile.ZipFile(rf_dir / m["zip"]) for tag, m in RF_SETS.items()}
    for c in pool:
        if id(c) in drop:
            continue
        s, meta = c["split"], RF_SETS[c["set"]]
        data = zips[c["set"]].read(c["member"])
        dst = ds / "images" / s / f"{c['name']}.jpg"
        w, h = c["w"], c["h"]
        if c["k"] or c["hw"] not in (None, 1.0):
            img = np.ascontiguousarray(np.rot90(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR), c["k"]))
            if c["hw"] not in (None, 1.0):
                side = img.shape[0]
                w, h = (round(side / c["hw"]), side) if c["hw"] > 1 else (side, round(side * c["hw"]))
                img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(dst), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        else:
            dst.write_bytes(data)
        lines = [f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}" for cx, cy, bw, bh in c["boxes"]]
        (ds / "labels" / s / f"{c['name']}.txt").write_text("".join(ln + "\n" for ln in lines))
        if s == "train":
            entries.append(str(dst))
        written[f"{c['set']} {s}"] += 1
        written[f"boxes {s}"] += len(lines)
        written[f"background {s}"] += not lines
        rows.append(dict(name=c["name"], source=meta["source"], split=s, boxes=len(lines), width=w, height=h,
                         url=f"{meta['zip']}:{c['member']}", origin=meta["origin"], licence="CC BY 4.0",
                         author=meta["author"], scene=c["scene"], rotated=90 * c["k"], frame_hw=c["hw"] or ""))
    for z in zips.values():
        z.close()
    rep["written"] = written
    return entries


def build(items: list[dict], raw: Path, ds: Path, video: dict, rf_dir: Path) -> Path:
    """Write the YOLO dataset, a fixed-seed held-out split per source, and a manifest."""
    if ds.exists():
        shutil.rmtree(ds)
    for s in ("train", "val", "val_video"):
        (ds / "images" / s).mkdir(parents=True)
        (ds / "labels" / s).mkdir(parents=True)
    rng = np.random.default_rng(SEED)
    split = {}
    for src in sorted({it["source"] for it in items}):
        names = sorted(it["name"] for it in items if it["source"] == src)
        n_val = max(1, round(VAL_FRAC * len(names)))
        for j, i in enumerate(rng.permutation(len(names))):
            split[names[i]] = "val" if j < n_val else "train"
    train_list, rows = [], []
    for it in sorted(items, key=lambda r: r["name"]):
        src = raw / f"{it['name']}.jpg"
        try:
            with Image.open(src) as im:
                if im.getexif().get(0x0112, 1) != 1:
                    continue                              # EXIF would turn the picture away from its boxes
        except OSError:
            continue
        img = cv2.imread(str(src), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        if img is None:
            continue
        h, w = img.shape[:2]
        lines = yolo_lines(it["boxes"], w, h, it["norm"])
        if not lines:
            continue
        s = split[it["name"]]
        cv2.imwrite(str(ds / "images" / s / f"{it['name']}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        (ds / "labels" / s / f"{it['name']}.txt").write_text("\n".join(lines) + "\n")
        copies = [ds / "images" / s / f"{it['name']}.jpg"]
        if s == "train":
            blurred, blines = motion_blur(img, lines, rng)
            mb = ds / "images" / s / f"{it['name']}_mb.jpg"
            cv2.imwrite(str(mb), blurred, [cv2.IMWRITE_JPEG_QUALITY, 95])
            (ds / "labels" / s / f"{it['name']}_mb.txt").write_text("\n".join(blines) + "\n")
            copies.append(mb)
            repeat = CRICKET_REPEAT if it["source"] == "openimages_cricket" else 1
            train_list += [str(p) for p in copies] * repeat
        rows.append(dict(name=it["name"], source=it["source"], split=s, boxes=len(lines), width=w, height=h,
                         url=it["url"], origin=it["origin"], licence=it["licence"], author=it["author"]))
    train_list += write_video(video, rf_dir, ds, len(train_list), rows)
    (ds / "train.txt").write_text("\n".join(train_list) + "\n")
    with open(ds / "manifest.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=MANIFEST, restval="")
        wr.writeheader()
        wr.writerows(rows)
    src = {r["name"]: r["source"] for r in rows}
    share = Counter(src[Path(p).stem.removesuffix("_mb")] for p in train_list)
    video["report"]["train_share"] = {k: round(v / len(train_list), 3) for k, v in share.most_common()}
    head = f"path: {ds}\ntrain: train.txt\nnames:\n  0: ball\n"
    (ds / "val_photo.yaml").write_text(head + "val: images/val\n")
    (ds / "val_video.yaml").write_text(head + "val: images/val_video\n")
    yaml = ds / "data.yaml"
    yaml.write_text(head + "val: [images/val, images/val_video]\n")   # best.pt is picked on both
    return yaml


def phash(img: np.ndarray) -> np.ndarray:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    small = cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    d = dct(dct(small, axis=0, norm="ortho"), axis=1, norm="ortho")[:8, :8].ravel()
    return np.packbits(d > np.median(d[1:]))


def thumb(img: np.ndarray) -> np.ndarray:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    t = cv2.resize(g, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
    t -= t.mean()
    return t / (np.linalg.norm(t) + 1e-6)


def frames(path: Path, tag: str):
    cap = cv2.VideoCapture(str(path))
    i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        yield f"{tag}#{i}", f
        i += 1
    cap.release()


def reference_frames(clips: Path):
    """Every frame of the three Exp 3 clips, then every frame of three clips from render.py."""
    for name in ("test3", "test4", "test5"):
        path = clips / f"{name}.mp4"
        if not path.exists():
            sys.exit(f"missing {path}; pass --clips with the folder holding the Exp 3 clips")
        yield from frames(path, name)
    sys.path[:0] = [str(ROOT / "server"), str(ROOT / "paper" / "experiments")]
    from synth import Camera, fly, grid   # noqa: E402
    from render import render            # noqa: E402
    cam = Camera(end="striker", back_m=2.8, height_m=1.7)
    with tempfile.TemporaryDirectory() as tmp:
        for i in (0, 37, 74):
            clip = Path(tmp) / f"render_{i}.mp4"
            render(fly(grid()[i]), cam, clip, fps=60.0)
            yield from frames(clip, f"render{i}")


def leakage_check(ds: Path, clips: Path) -> dict:
    refs, rh, rt = [], [], []
    for name, f in reference_frames(clips):
        refs.append((name, None))
        rh.append(phash(f))
        rt.append(thumb(f))
    rh = np.stack(rh)
    popcount = np.array([bin(i).count("1") for i in range(256)], np.uint8)
    files = sorted((ds / "images").rglob("*.jpg"))
    best, flagged = 64, []
    for p in files:
        img = cv2.imread(str(p))
        for variant in (img, np.ascontiguousarray(img[:, ::-1])):
            dist = popcount[np.bitwise_xor(rh, phash(variant))].sum(axis=1)
            j = int(dist.argmin())
            best = min(best, int(dist[j]))
            for k in np.flatnonzero(dist <= HASH_DIST):
                corr = float(thumb(variant) @ rt[k])
                if corr >= THUMB_CORR:
                    flagged.append((p.name, refs[k][0], int(dist[k]), round(corr, 3)))
    n_real = sum(1 for n, _ in refs if n.startswith("test"))
    report = dict(images=len(files), reference_frames=len(refs), real_frames=n_real, rendered_frames=len(refs) - n_real,
                  min_hamming=best, hash_threshold=HASH_DIST, thumb_corr_threshold=THUMB_CORR, duplicates=flagged)
    print(f"  leakage check: {len(files)} images x2 (mirrored) vs {len(refs)} frames, "
          f"min Hamming {best}/64, duplicates {len(flagged)}")
    return report


def cache_mode(ds: Path, limit: float = 15e9, keep_free: float = 20e9):
    """Disk cache only when the decoded 640 px arrays stay under `limit` and leave `keep_free` bytes on disk."""
    need = 0
    for p in (ds / "images").rglob("*.jpg"):
        with Image.open(p) as im:
            w, h = im.size
        r = 640 / max(w, h)
        need += round(w * r) * round(h * r) * 3 + 128
    free = shutil.disk_usage(ds).free
    ok = need < limit and free - need >= keep_free
    print(f"  disk cache would take {need / 1e9:.1f} GB with {free / 1e9:.1f} GB free: {'on' if ok else 'off'}")
    return "disk" if ok else False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=ROOT / "server" / "datasets" / "ball_detector")
    ap.add_argument("--clips", type=Path, default=ROOT, help="folder with test3.mp4, test4.mp4, test5.mp4")
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--out", type=Path, default=ROOT / "server" / "models" / "cricket_ball.pt")
    ap.add_argument("--roboflow", type=Path, default=ROOT.parent / "pocket-drs-data" / "downloads",
                    help="folder with the two Roboflow zips")
    ap.add_argument("--no-train", action="store_true", help="build the dataset and run the leakage check only")
    args = ap.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)

    print("selecting images")
    items = open_images(work) + coco(work)
    items = download(dedupe(items), work / "raw")
    print("reading the Roboflow video frames")
    video = load_video(args.roboflow.resolve())
    print("building dataset")
    yaml = build(items, work / "raw", work / "ds", video, args.roboflow.resolve())
    (work / "video.json").write_text(json.dumps(video["report"], indent=2))
    print(json.dumps(video["report"], indent=2))
    report = leakage_check(work / "ds", args.clips)
    report["manifest_sha256"] = sha256(work / "ds" / "manifest.csv")
    (work / "leakage.json").write_text(json.dumps(report, indent=2))
    if report["duplicates"]:
        print("near duplicates of test or rendered frames found, not training:", report["duplicates"][:10])
        return 1
    if args.no_train:
        return 0

    from ultralytics import YOLO
    base = fetch(BASE_URL.format(args.model), work / args.model)
    print(f"training from {args.model} (sha256 {sha256(base)[:16]})")
    model = YOLO(str(base))
    model.train(data=str(yaml), epochs=args.epochs, imgsz=640, batch=args.batch, device=args.device, workers=1,
                cache=cache_mode(work / "ds"), seed=SEED, deterministic=True, single_cls=True, scale=0.9, patience=15,
                plots=False, project=str(work / "runs"), name="ball", exist_ok=True)
    best = work / "runs" / "ball" / "weights" / "best.pt"
    metrics = {}
    for part in ("photo", "video"):
        for size in (640, 1280):
            m = YOLO(str(best)).val(data=str(work / "ds" / f"val_{part}.yaml"), imgsz=size,
                                    batch=max(1, args.batch * 640 // size), device=args.device, workers=1, plots=False,
                                    verbose=False, project=str(work / "runs"), name=f"val_{part}{size}", exist_ok=True)
            metrics[f"{part}_{size}"] = dict(precision=round(float(m.box.mp), 4), recall=round(float(m.box.mr), 4),
                                             map50=round(float(m.box.map50), 4), map50_95=round(float(m.box.map), 4))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(best, args.out)
    shutil.copyfile(work / "ds" / "manifest.csv", args.out.parent / "detector_manifest.csv")
    summary = dict(base=args.model, base_sha256=sha256(base), epochs=args.epochs, weights=str(args.out),
                   weights_sha256=sha256(args.out), val=metrics)
    (work / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
