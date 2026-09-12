# face_detector.py
# This module handles all face detection logic using MediaPipe.
#
# MediaPipe is Google's ML library for face landmark detection.
# It finds 468 points on your face (eyes, nose, mouth, jawline etc.)
# and gives us their (x, y) coordinates — all in real time.

import cv2
import mediapipe as mp
import numpy as np

# ---------------------------------------------------------------
# Initialise MediaPipe Face Mesh
# Face Mesh finds 468 landmarks on a face.
#
# static_image_mode=True  → we're sending individual frames,
#                            not a continuous video stream from
#                            MediaPipe's perspective
# max_num_faces=1         → only detect one face (the user's)
# refine_landmarks=True   → also detect detailed eye & lip points
# min_detection_confidence → how confident it must be before
#                            reporting a face (0.5 = 50%)
# ---------------------------------------------------------------
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=True,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
)


# ---------------------------------------------------------------
# These are the landmark indices for the LEFT and RIGHT eyes.
# MediaPipe gives us 468 points — these specific ones form
# the outline of each eye. We use them for blink detection later.
#
# LEFT EYE (from the face's perspective, appears on right of screen)
# RIGHT EYE (from the face's perspective, appears on left of screen)
# ---------------------------------------------------------------
LEFT_EYE_INDICES  = [362, 382, 381, 380, 374, 373, 390, 249,
                     263, 466, 388, 387, 386, 385, 384, 398]

RIGHT_EYE_INDICES = [33, 7, 163, 144, 145, 153, 154, 155,
                     133, 173, 157, 158, 159, 160, 161, 246]

# Specific points used to calculate Eye Aspect Ratio (EAR) for blink detection
# Format: [top, bottom, left, right] — we'll use these in liveness.py
LEFT_EYE_EAR_POINTS  = [386, 374, 362, 263]
RIGHT_EYE_EAR_POINTS = [159, 145, 33, 133]


# ---------------------------------------------------------------
# FUNCTION: detect_face
# Takes a raw image (as bytes, received from the browser),
# runs MediaPipe on it, and returns:
#   - face_found: True/False
#   - landmarks: list of (x, y) pixel coordinates for all 468 points
#   - image dimensions: needed by the browser to scale coordinates
# ---------------------------------------------------------------
def detect_face(image_bytes: bytes) -> dict:
    # Step 1: Convert raw bytes → numpy array → OpenCV image
    # The browser sends us a JPEG file as bytes.
    # np.frombuffer turns those bytes into a number array.
    # cv2.imdecode turns that array into an actual image we can process.
    np_arr = np.frombuffer(image_bytes, np.uint8)
    image  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if image is None:
        return {"face_found": False, "error": "Could not decode image"}

    # Step 2: Get image dimensions
    height, width = image.shape[:2]

    # Step 3: Convert BGR to RGB
    # OpenCV loads images in BGR (Blue-Green-Red) order by default.
    # MediaPipe expects RGB (Red-Green-Blue).
    # This one line swaps the colour channels.
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # Step 4: Run MediaPipe face detection
    results = face_mesh.process(rgb_image)

    # Step 5: Check if any face was found
    if not results.multi_face_landmarks:
        return {
            "face_found": False,
            "landmarks": [],
            "width": width,
            "height": height,
        }

    # Step 6: Extract landmark coordinates
    # MediaPipe gives coordinates as fractions (0.0 to 1.0) of the image size.
    # We multiply by width/height to get actual pixel positions.
    # This is important — the browser needs pixel positions to draw on canvas.
    face_landmarks = results.multi_face_landmarks[0]  # first (only) face

    landmarks = []
    for landmark in face_landmarks.landmark:
        x = int(landmark.x * width)   # fraction → pixel
        y = int(landmark.y * height)
        landmarks.append({"x": x, "y": y})

    # Step 7: Extract just the eye landmarks separately
    # We'll need these specifically for blink detection in Step 5
    left_eye  = [landmarks[i] for i in LEFT_EYE_INDICES]
    right_eye = [landmarks[i] for i in RIGHT_EYE_INDICES]

    return {
        "face_found": True,
        "landmarks": landmarks,          # all 468 points
        "left_eye":  left_eye,           # 16 points around left eye
        "right_eye": right_eye,          # 16 points around right eye
        "width":  width,
        "height": height,
    }