"""Pure landmark, image-evidence, and head-pose helpers for webcam tracking."""

from __future__ import annotations

import numpy as np

from amble.analysis.quality import EyeEvidence

# MediaPipe Face Landmarker indices. Naming follows anatomical left/right.
LEFT_EAR = (362, 385, 387, 263, 373, 380)
RIGHT_EAR = (33, 160, 158, 133, 153, 144)
LEFT_EYE_OUTLINE = (
    362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398,
)
RIGHT_EYE_OUTLINE = (
    33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246,
)
LEFT_IRIS = (473, 474, 475, 476, 477)
RIGHT_IRIS = (468, 469, 470, 471, 472)


def landmark_points(
    landmarks, indices: tuple[int, ...], width: int, height: int
) -> list[tuple[float, float]]:
    if not landmarks or max(indices) >= len(landmarks):
        return []
    return [
        (landmarks[index].x * width, landmarks[index].y * height)
        for index in indices
    ]


def crop_evidence(
    cv2_module,
    gray: np.ndarray,
    points: list[tuple[float, float]],
    ear: float | None,
    blink: float | None,
) -> EyeEvidence:
    height, width = gray.shape[:2]
    if not points:
        return EyeEvidence()
    xs = np.array([point[0] for point in points])
    ys = np.array([point[1] for point in points])
    eye_width = float(xs.max() - xs.min())
    eye_height = float(ys.max() - ys.min())
    pad_x = max(3, int(eye_width * 0.18))
    pad_y = max(3, int(max(eye_height, 8) * 0.45))
    x1 = max(0, int(xs.min()) - pad_x)
    x2 = min(width, int(xs.max()) + pad_x + 1)
    y1 = max(0, int(ys.min()) - pad_y)
    y2 = min(height, int(ys.max()) + pad_y + 1)
    crop = gray[y1:y2, x1:x2]
    sharpness = (
        float(cv2_module.Laplacian(crop, cv2_module.CV_64F).var())
        if crop.size >= 25
        else 0.0
    )
    brightness = float(crop.mean()) if crop.size else 0.0
    dark = float(np.mean(crop <= 20)) if crop.size else 1.0
    bright = float(np.mean(crop >= 245)) if crop.size else 1.0
    edge_safe = (
        xs.min() > width * 0.015
        and xs.max() < width * 0.985
        and ys.min() > height * 0.015
        and ys.max() < height * 0.985
    )
    geometry = eye_width >= 8 and eye_height >= 1 and eye_width / max(eye_height, 1) < 15
    return EyeEvidence(
        True,
        ear,
        blink,
        eye_width,
        eye_height,
        sharpness,
        brightness,
        dark,
        bright,
        edge_safe,
        geometry,
    )


def blendshape_map(result) -> dict[str, float]:
    if not getattr(result, "face_blendshapes", None):
        return {}
    return {
        item.category_name: float(item.score)
        for item in result.face_blendshapes[0]
    }


def pose(cv2_module, result) -> tuple[float | None, float | None, float | None]:
    matrices = getattr(result, "facial_transformation_matrixes", None)
    if not matrices:
        return None, None, None
    matrix = np.asarray(matrices[0], dtype=float)
    if matrix.shape[0] < 3 or matrix.shape[1] < 3:
        return None, None, None
    try:
        angles = cv2_module.RQDecomp3x3(matrix[:3, :3])[0]
        return float(angles[1]), float(angles[0]), float(angles[2])
    except cv2_module.error:
        return None, None, None


__all__ = [
    "LEFT_EAR",
    "LEFT_EYE_OUTLINE",
    "LEFT_IRIS",
    "RIGHT_EAR",
    "RIGHT_EYE_OUTLINE",
    "RIGHT_IRIS",
    "blendshape_map",
    "crop_evidence",
    "landmark_points",
    "pose",
]
