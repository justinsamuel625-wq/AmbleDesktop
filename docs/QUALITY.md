# Webcam measurement-quality model

This model answers whether each eye is currently visible and measurable enough to retain as a valid webcam-proxy sample. It does **not** estimate diagnostic, clinical, or medical confidence.

## Landmark backend

Amble uses the MediaPipe Face Landmarker task with the official local `face_landmarker.task` model. It returns a dense facial mesh, refined eye/iris landmarks, facial transformation matrices, and eye-blink blendshapes. Eye centers displayed by Amble are iris-center proxies, not anatomical pupil measurements.

## Eye openness

Two established signals are retained:

- MediaPipe `eyeBlinkLeft` and `eyeBlinkRight` blendshape coefficients.
- Eye Aspect Ratio (EAR): `(||p2−p6|| + ||p3−p5||) / (2||p1−p4||)` using six eyelid landmarks.

Default classifications are:

| State | Default evidence |
|---|---|
| OPEN | blink < 0.35 and EAR ≥ 0.23 |
| SQUINTING | blink ≥ 0.35 or 0.16 ≤ EAR < 0.23 |
| CLOSED | blink ≥ 0.70 or EAR < 0.16 |
| UNCERTAIN | landmarks absent or eye width below the minimum reliable image-space resolution |

These defaults are configurable in `QualityThresholds`. They are engineering rejection thresholds, not validated clinical cutoffs.

## Per-eye score

Each eye receives a 0–100 score:

| Component | Weight |
|---|---:|
| Openness | 34% |
| Image-space eye size | 18% |
| Local Laplacian sharpness | 16% |
| Local eye-region exposure | 14% |
| Landmark geometry and frame-edge safety | 10% |
| Rolling detection stability | 8% |

`CLOSED`, `SQUINTING`, and `UNCERTAIN` cap an eye at 12%, 55%, and 35% respectively. The overall score starts with the lower of the two eye scores, then applies face-framing, head-pose, and temporal-stability factors. A strong eye can therefore never average away an unreliable fellow eye.

## Default image-space thresholds

Eye-distance guidance uses measured eye width in camera pixels. The defaults are:

- eye width below 28 px: low resolution; openness becomes uncertain;
- preferred eye width 40–75 px: ideal image-space distance/resolution;
- eye width above 105 px: excessively large at the default profile;
- the Hardware slider can move the preferred range from approximately 28–55 px (farther) through 40–75 px (balanced) to 55–99 px (closer/higher resolution);
- changing this range affects only the 18% image-size component and distance guidance; it cannot override closure, blur, lighting, pose, visibility, or stability rejection;
- face cropping remains an independent penalty;
- eye-region Laplacian variance below 35: low sharpness; 85 or above: good;
- mean eye-region intensity below 50: too dark; above 225: overexposed;
- valid pose: |yaw| ≤25°, |pitch| ≤20°, |roll| ≤20°;
- temporal window: 0.75 seconds;
- valid binocular threshold: 70% by default and adjustable on Hardware.

The distance state is only an image-space quality category. It is not physical distance in centimeters. The selected minimum, maximum, quality threshold, tracker backend, and camera resolution are copied into each session's `metadata.json`.

## Raw-data provenance

Every raw row retains `left_eye_valid`, `right_eye_valid`, `binocular_valid`, per-eye and overall quality, openness, eye width, sharpness, local lighting states, pose validity, face quality, distance category, live guidance, the applied threshold, and JSON reasons. Invalid measurements remain available for audit and method development.
