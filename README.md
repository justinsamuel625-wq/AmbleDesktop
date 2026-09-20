# Amble Research 0.1

Amble Research is a professional desktop research prototype for timestamped binocular eye-behavior experiments. It is a **research measurement tool and is not a medical diagnostic or treatment device**. The webcam backend is a MediaPipe landmark/blendshape research proxy with OpenCV camera acquisition and is not clinically equivalent to an ophthalmic eye tracker.

Version 0.1 includes a desktop shell, explicit camera access, device selection and preview, replaceable tracker interfaces, nine-point calibration quality reporting, fixation/smooth-pursuit/vergence-proxy/external near–far protocols, pre/intervention/post phases, immediate raw recording, event markers, physical-distance keys, quality-gated metrics, Plotly analytics, raw-row exploration, and structured research exports.

## Install and run

Python 3.11–3.14 is supported. From PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
amble
```

The application starts with a deterministic simulator so every workflow can be tested without hardware. Open **Hardware**, select the webcam backend, and click **Request camera access / start preview** to invoke operating-system camera permission and begin capture. Amble never starts webcam access or video recording silently.

Data is stored by default under `~/Amble Research Data`. Set `AMBLE_DATA_DIR` to select a different root:

```powershell
$env:AMBLE_DATA_DIR = "D:\Research\AmbleData"
amble
```

## Research workflow

1. Create/select a coded subject identifier.
2. Select the simulator or explicitly connect a camera.
3. Run the nine-point calibration and review per-session quality.
4. Configure the experiment-specific fields: fixation position/size, pursuit trajectory/rate/amplitude, or the preliminary screen-vergence proxy parameters.
5. Record automatic pre, intervention, and post phases.
6. For an external near–far protocol, click the known physical distance as it changes.
7. Stop/finalize, review quality-gated metrics, and click through to raw rows.

Camera video is off by default. Enabling it is explicit, works only with the webcam backend, and keeps a red **RECORDING VIDEO + DATA** indicator visible throughout capture.

## Tracking backend

`EyeTracker` defines connect/disconnect/stream boundaries and normalized per-eye output. The webcam adapter uses Google's MediaPipe Face Landmarker with its refined eye/iris landmarks and face blendshapes. OpenCV remains responsible for camera acquisition, local image-quality measurements, and overlays. Output is still a webcam research proxy and is never labeled clinical gaze or true vergence. Pupil Labs, Tobii, infrared binocular hardware, TrueDepth, or VR tracking can implement the same interface.

OpenFace is not bundled because its platform-native executable and models have independent installation/licensing requirements. An operational `OpenFaceEyeTracker` subprocess adapter consumes the live CSV emitted by `FeatureExtraction`, including per-eye gaze vectors, head pose, confidence, frame identity, and source timing. Set `OPENFACE_FEATURE_EXTRACTION` to the installed executable, then choose OpenFace on the Hardware page. Its gaze-vector projection is still labeled estimated and requires calibration.

## Hardware and camera diagnostics

Amble requires exactly one OpenCV distribution: `opencv-contrib-python>=4.14,<5`. The contrib build is required by the MediaPipe landmark dependency. Do not install `opencv-python`, either headless variant, or multiple OpenCV variants in the same environment. MediaPipe is pinned to `0.10.35`, and the official Face Landmarker model is packaged locally for offline runtime. The launch script uses the repository's `.venv`, not global Python.

Verify the active environment and OpenCV installation from the project directory:

```powershell
.\.venv\Scripts\python.exe -c "import sys, cv2; print(sys.executable); print(cv2.__file__); print(cv2.__version__); print(hasattr(cv2, 'CascadeClassifier'))"
```

The final value must be `True`. In the application:

1. Open **Hardware** and select **Webcam — OpenCV research proxy**.
2. Click **Scan cameras**. Amble tests MSMF, DirectShow, and automatic backend selection and lists only indices that return a real frame.
3. Select the desired device and click **Request camera access / start preview**.
4. Drag the vertical preview divider or choose **Expanded**, **Medium**, or **Collapsed**. Collapsing hides rendering only; acquisition and quality updates continue.
5. Set the configurable **Minimum binocular quality** threshold (70% by default).
6. Adjust **Camera distance preference**. The balanced default prefers 40–75 px eye width; the displayed values are image-space resolution, not centimeters.
7. Keep the compact live metrics visible while using the scrollable setup and full diagnostic detail below.
8. Expand **Why this quality score?** to see the evidence behind each score.
9. Toggle **Show facial/eye landmark debug overlay** to show or hide face/eye contours, labeled iris-center proxies, and quality guidance.

If no camera appears, open **Windows Settings → Privacy & security → Camera** and enable camera access plus desktop-app access. Close applications such as Teams, Zoom, OBS, browsers, or the Windows Camera app if they have exclusive use of the device, check any physical privacy shutter, and scan again. Some laptops expose separate infrared and visible-light devices; select the device whose preview shows a normal visible image.

Amble never substitutes simulated data after a webcam failure. It displays the technical error and leaves acquisition disconnected. To use synthetic data deliberately, click **Use Simulator Instead** or select the simulator backend and start it explicitly.

### Measurement-quality model

The prior confidence was simply `65% × number of Haar eye boxes / 2`; it did not measure eyelid openness, image resolution, blur, exposure, pose, or temporal stability. That is why a squinting eye could retain moderate confidence.

The current model calculates left and right eye quality independently using MediaPipe eyelid/iris landmarks, `eyeBlinkLeft`/`eyeBlinkRight` blendshapes, Eye Aspect Ratio, configurable pixel-based eye width, local Laplacian sharpness, local brightness/clipping, landmark geometry, frame-edge safety, face framing, head pose, and a rolling 0.75-second detection window. Overall binocular quality is governed by the worse eye; it is not an average that can conceal one unreliable eye. Closed and squinting classifications cap the affected eye's score, and low-resolution eyelids are marked `UNCERTAIN` rather than falsely claiming open or closed.

Low-quality rows are retained in CSV/Parquet with their per-eye validity, scores, openness, pixel widths, sharpness, exposure state, pose validity, distance category, guidance, threshold, and JSON rejection reasons. See [quality model and thresholds](docs/QUALITY.md).

## Data format and reproducibility

Each session folder contains:

```text
session_YYYY_MM_DD_HHMMSS_id/
  metadata.json
  calibration.json          # when calibration was completed
  raw_eye_tracking.csv      # append-only acquisition source
  raw_eye_tracking.parquet  # analysis-optimized exact row copy
  events.csv
  derived_metrics.csv
  camera_video.mp4          # only after explicit opt-in
```

SQLite indexes subjects, sessions, configurations, calibration, quality, and derived metric provenance. Metadata records the software version, tracker, camera resolution, preferred eye-width range, quality threshold, experiment definition, clocks, environment, and storage formats. Pursuit amplitude and screen-vergence-proxy amplitude are normalized screen-coordinate half-ranges, not pixels or visual degrees. Analytics reloads Parquet/CSV after recording closes; the Raw Data page opens that same path. See [metric definitions](docs/METRICS.md) and [architecture](docs/ARCHITECTURE.md).

## Tests

```powershell
pytest
```

Tests cover typed experiment conversion, experiment-specific controls, all implemented session starts, numeric bounds, formulas, adjustable distance quality, preview collapse behavior, quality suppression, trajectory bounds, simulated binocular acquisition, CSV/Parquet row identity, timestamps, and metadata reproducibility. A headless UI smoke test can be run with `QT_QPA_PLATFORM=offscreen`.

## Known limitations

- Webcam iris-center coordinates are workflow proxies, not accurate point-of-gaze measurements. A validated OpenFace or hardware adapter is the next acquisition milestone.
- MediaPipe openness and quality indicators improve rejection of unusable frames but are not clinical measurements. EAR/blink thresholds should be validated for the study population and camera configuration before inferential use.
- Calibration reports error but v0.1 does not fit a gaze transform for the OpenCV proxy.
- Corrective-saccade detection, robust blink interpolation, sampling-aware velocity metrics, per-trial comparison statistics, and LSL clock correction are reserved for later validated releases.
- Flat-screen vergence is labeled as a proxy. True vergence requires known camera/eye geometry or validated binocular hardware.
- Export currently copies the structured session folder and supports filtered CSV plus native CSV/Parquet/JSON artifacts.

## Future integration

Add hardware under `amble.tracking.EyeTracker`; add EEG/HR/IMU/VR sources through `SensorStream`. Preserve UTC nanoseconds, monotonic source time, event markers, and source-specific clock metadata. An LSL adapter should record time-correction estimates alongside each stream rather than overwriting source timestamps.
