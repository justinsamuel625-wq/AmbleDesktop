import pytest

from amble.quality import (
    DistanceQuality, EyeEvidence, EyeOpenness, QualityThresholds,
    TemporalQualityWindow, classify_openness, compose_quality,
    distance_quality, eye_aspect_ratio,
)


def evidence(ear=.30, blink=.05, width=62, sharp=120, brightness=125):
    return EyeEvidence(True, ear, blink, width, 18, sharp, brightness, 0, 0, True, True)


def test_ear_and_blink_classify_open_squint_closed():
    thresholds = QualityThresholds()
    open_points = [(0, 0), (2, -2), (8, -2), (10, 0), (8, 2), (2, 2)]
    closed_points = [(0, 0), (2, -.4), (8, -.4), (10, 0), (8, .4), (2, .4)]
    assert eye_aspect_ratio(open_points) == pytest.approx(.4)
    assert eye_aspect_ratio(closed_points) == pytest.approx(.08)
    assert classify_openness(.30, .05, thresholds) == EyeOpenness.OPEN
    assert classify_openness(.20, .45, thresholds) == EyeOpenness.SQUINTING
    assert classify_openness(.30, .85, thresholds) == EyeOpenness.CLOSED
    assert classify_openness(.10, .05, thresholds) == EyeOpenness.CLOSED


def test_bad_eye_governs_binocular_quality_and_validity():
    thresholds = QualityThresholds(minimum_binocular_quality=.70)
    result = compose_quality(
        evidence(), evidence(ear=.12, blink=.90), 640, .50, False,
        (0, 0, 0), 1, 1, thresholds,
    )
    assert result.left.score >= 70
    assert result.right.score <= 12
    assert result.overall <= result.right.score
    assert not result.right.valid
    assert not result.binocular_valid
    assert result.guidance == "Open right eye fully"


def test_low_resolution_eye_openness_is_uncertain_not_falsely_closed():
    thresholds = QualityThresholds()
    result = compose_quality(
        evidence(width=15, ear=.05, blink=.9), evidence(width=15, ear=.05, blink=.9),
        640, .15, False, (0, 0, 0), 1, 1, thresholds,
    )
    assert result.left.openness == EyeOpenness.UNCERTAIN
    assert result.right.openness == EyeOpenness.UNCERTAIN
    assert not result.binocular_valid
    assert result.guidance == "Move closer"


@pytest.mark.parametrize(("bad_side", "blink", "ear", "state", "guidance"), [
    ("left", .9, .10, EyeOpenness.CLOSED, "Open left eye fully"),
    ("right", .9, .10, EyeOpenness.CLOSED, "Open right eye fully"),
    ("left", .45, .20, EyeOpenness.SQUINTING, "Open left eye fully"),
    ("right", .45, .20, EyeOpenness.SQUINTING, "Open right eye fully"),
])
def test_each_eye_closure_or_squint_is_rejected_independently(bad_side, blink, ear, state, guidance):
    bad, good = evidence(ear=ear, blink=blink), evidence()
    left, right = (bad, good) if bad_side == "left" else (good, bad)
    result = compose_quality(left, right, 640, .5, False, (0, 0, 0), 1, 1, QualityThresholds())
    affected = result.left if bad_side == "left" else result.right
    unaffected = result.right if bad_side == "left" else result.left
    assert affected.openness == state
    assert affected.score < 70 < unaffected.score
    assert not result.binocular_valid
    assert result.guidance == guidance


def test_blur_darkness_and_extreme_pose_each_invalidate_measurement():
    good = evidence()
    blurred = evidence(sharp=5)
    dark = evidence(brightness=15)
    blur_result = compose_quality(blurred, good, 640, .5, False, (0, 0, 0), 1, 1, QualityThresholds())
    dark_result = compose_quality(dark, good, 640, .5, False, (0, 0, 0), 1, 1, QualityThresholds())
    pose_result = compose_quality(good, good, 640, .5, False, (40, 0, 0), 1, 1, QualityThresholds())
    assert not blur_result.binocular_valid and blur_result.left.score <= 60
    assert blur_result.guidance == "Hold still and improve focus"
    assert not dark_result.binocular_valid and dark_result.left.score <= 60
    assert dark_result.guidance == "Improve lighting"
    assert not pose_result.binocular_valid
    assert pose_result.guidance == "Turn toward camera"


def test_quality_threshold_changes_validity_without_discarding_score():
    eye = evidence(sharp=75)
    permissive = compose_quality(eye, eye, 640, .5, False, (0, 0, 0), 1, 1, QualityThresholds(minimum_binocular_quality=.50))
    strict = compose_quality(eye, eye, 640, .5, False, (0, 0, 0), 1, 1, QualityThresholds(minimum_binocular_quality=.99))
    assert permissive.overall == strict.overall
    assert permissive.binocular_valid
    assert not strict.binocular_valid


@pytest.mark.parametrize(("eye_width_px", "expected"), [
    (20, DistanceQuality.TOO_FAR), (39, DistanceQuality.TOO_FAR),
    (40, DistanceQuality.IDEAL), (75, DistanceQuality.IDEAL),
    (76, DistanceQuality.TOO_CLOSE),
])
def test_distance_quality_uses_configurable_eye_pixel_range(eye_width_px, expected):
    assert distance_quality(eye_width_px, QualityThresholds()) == expected


def test_preferred_eye_range_changes_only_resolution_component():
    eye = evidence(width=62)
    balanced = compose_quality(eye, eye, 640, .5, False, (0, 0, 0), 1, 1, QualityThresholds())
    closer = compose_quality(
        eye, eye, 640, .5, False, (0, 0, 0), 1, 1,
        QualityThresholds(eye_width_min_px=49, preferred_eye_width_min_px=70, preferred_eye_width_max_px=95, eye_width_too_close_px=125),
    )
    assert balanced.left.size_state == "GOOD"
    assert closer.left.size_state == "ACCEPTABLE"
    assert closer.left.score < balanced.left.score
    assert closer.left.openness == balanced.left.openness == EyeOpenness.OPEN


def test_closed_eye_remains_invalid_at_ideal_configured_eye_size():
    thresholds = QualityThresholds(preferred_eye_width_min_px=55, preferred_eye_width_max_px=70)
    result = compose_quality(evidence(width=62, ear=.1, blink=.9), evidence(width=62), 640, .5, False, (0, 0, 0), 1, 1, thresholds)
    assert result.left.size_state == "GOOD"
    assert result.left.openness == EyeOpenness.CLOSED
    assert result.left.score <= 12
    assert not result.binocular_valid


def test_temporal_stability_penalizes_flickering_detection():
    window = TemporalQualityWindow(1.0)
    for index in range(10):
        left, right = window.update(index * 100_000_000, index % 2 == 0, True)
    assert left == .5
    assert right == 1.0
