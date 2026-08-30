from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

_MIN_MATCHES = 12
_RATIO = 0.75
_RANSAC_THRESH = 3.0


@dataclass
class CartographyState:
    frames: list[np.ndarray] = field(default_factory=list)
    transforms: list[np.ndarray] = field(default_factory=list)  # each 2x3 → mosaic coords
    mosaic: np.ndarray | None = None
    last_error: str = ""


def start_session(frame_bgr: np.ndarray) -> CartographyState:
    image = np.ascontiguousarray(frame_bgr)
    identity = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)
    return CartographyState(frames=[image], transforms=[identity], mosaic=image.copy(), last_error="")


def append_frame(state: CartographyState, frame_bgr: np.ndarray) -> bool:
    """Register frame against the last accepted frame (SCANS-style affine)."""
    state.last_error = ""
    if state.mosaic is None or not state.frames:
        rebuilt = start_session(frame_bgr)
        state.frames = rebuilt.frames
        state.transforms = rebuilt.transforms
        state.mosaic = rebuilt.mosaic
        return True

    frame = np.ascontiguousarray(frame_bgr)
    relative = _estimate_affine_to_previous(state.frames[-1], frame)
    if relative is None:
        state.last_error = "配准失败，请与上一帧保持约 30%–50% 重叠后再截"
        return False

    # Maps new-frame pixels into current mosaic coordinates (pre-expansion).
    canvas_transform = _compose_affine(state.transforms[-1], relative)
    blended, shift_x, shift_y = _warp_blend(state.mosaic, frame, canvas_transform)
    if blended is None:
        state.last_error = "合成失败"
        return False

    if shift_x or shift_y:
        state.transforms = [_translate_affine(t, shift_x, shift_y) for t in state.transforms]
        canvas_transform = _translate_affine(canvas_transform, shift_x, shift_y)

    state.frames.append(frame)
    state.transforms.append(canvas_transform)
    state.mosaic = blended
    return True


def _estimate_affine_to_previous(prev: np.ndarray, new: np.ndarray) -> np.ndarray | None:
    prev_gray = _gray(prev)
    new_gray = _gray(new)
    orb = cv2.ORB_create(nfeatures=2500)
    kp_prev, des_prev = orb.detectAndCompute(prev_gray, None)
    kp_new, des_new = orb.detectAndCompute(new_gray, None)
    if des_prev is None or des_new is None or len(kp_prev) < 8 or len(kp_new) < 8:
        return None

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    pairs = matcher.knnMatch(des_new, des_prev, k=2)
    good: list[cv2.DMatch] = []
    for pair in pairs:
        if len(pair) != 2:
            continue
        best, second = pair
        if best.distance < _RATIO * second.distance:
            good.append(best)
    if len(good) < _MIN_MATCHES:
        return None

    src = np.float32([kp_new[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_prev[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    matrix, mask = cv2.estimateAffinePartial2D(
        src,
        dst,
        method=cv2.RANSAC,
        ransacReprojThreshold=_RANSAC_THRESH,
        maxIters=4000,
        confidence=0.99,
    )
    if matrix is None or mask is None or int(mask.sum()) < _MIN_MATCHES:
        return None
    return matrix.astype(np.float64)


def _compose_affine(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    a = np.vstack([first.astype(np.float64), [0.0, 0.0, 1.0]])
    b = np.vstack([second.astype(np.float64), [0.0, 0.0, 1.0]])
    return (a @ b)[:2, :]


def _translate_affine(matrix: np.ndarray, dx: float, dy: float) -> np.ndarray:
    out = matrix.astype(np.float64).copy()
    out[0, 2] += dx
    out[1, 2] += dy
    return out


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _warp_blend(
    mosaic: np.ndarray,
    frame: np.ndarray,
    canvas_transform: np.ndarray,
) -> tuple[np.ndarray | None, int, int]:
    mh, mw = mosaic.shape[:2]
    fh, fw = frame.shape[:2]
    mosaic_corners = np.float32([[0, 0], [mw, 0], [mw, mh], [0, mh]]).reshape(-1, 1, 2)
    frame_corners = np.float32([[0, 0], [fw, 0], [fw, fh], [0, fh]]).reshape(-1, 1, 2)
    warped_corners = cv2.transform(frame_corners, canvas_transform)
    all_pts = np.vstack([mosaic_corners.reshape(-1, 2), warped_corners.reshape(-1, 2)])
    min_x = int(np.floor(float(all_pts[:, 0].min())))
    min_y = int(np.floor(float(all_pts[:, 1].min())))
    max_x = int(np.ceil(float(all_pts[:, 0].max())))
    max_y = int(np.ceil(float(all_pts[:, 1].max())))
    width = max(1, max_x - min_x)
    height = max(1, max_y - min_y)
    shift_x = -min_x
    shift_y = -min_y
    shift = np.array([[1.0, 0.0, float(shift_x)], [0.0, 1.0, float(shift_y)]], dtype=np.float64)
    mosaic_m = shift
    frame_m = _compose_affine(shift, canvas_transform)

    channels = 1 if mosaic.ndim == 2 else mosaic.shape[2]
    if channels == 1:
        canvas = np.zeros((height, width), dtype=np.uint8)
    else:
        canvas = np.zeros((height, width, channels), dtype=np.uint8)

    warped_mosaic = cv2.warpAffine(
        mosaic,
        mosaic_m,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    warped_frame = cv2.warpAffine(
        frame,
        frame_m,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    if channels == 1:
        mask = warped_frame > 0
        canvas[:] = warped_mosaic
        canvas[mask] = warped_frame[mask]
    else:
        mask = np.any(warped_frame > 0, axis=2)
        canvas[:] = warped_mosaic
        canvas[mask] = warped_frame[mask]
    return canvas, int(shift_x), int(shift_y)
