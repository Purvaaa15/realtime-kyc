# face_match.py
# This module compares two faces — the live selfie and the ID card photo.
#
# HOW IT WORKS:
# face_recognition library converts any face image into a list of
# 128 numbers — called a "face encoding" or "embedding".
# This 128-number vector is a mathematical fingerprint of that face.
#
# Two photos of the SAME person → vectors are very close together
# Two photos of DIFFERENT people → vectors are far apart
#
# We measure "distance" between vectors using Euclidean distance.
# distance < 0.5  → very likely same person (strict)
# distance < 0.6  → likely same person (standard threshold)
# distance > 0.6  → likely different people

import face_recognition
import numpy as np
import cv2
import os

# ---------------------------------------------------------------
# MATCH THRESHOLD
# If distance between face embeddings is below this → match!
# 0.6 is the standard threshold used by face_recognition library.
# Lower = stricter (more false rejections)
# Higher = looser (more false acceptances)
# ---------------------------------------------------------------
MATCH_THRESHOLD = 0.6


# ---------------------------------------------------------------
# FUNCTION: get_face_encoding
# Takes an image (as numpy array) and returns the 128-number
# face encoding for the first face found in the image.
#
# Returns None if no face is found.
# ---------------------------------------------------------------
def get_face_encoding(image: np.ndarray):
    # If the image is small, upscale it first — small/low-res faces
    # produce noisier embeddings. This especially helps ID card
    # photos captured at an angle or from a distance.
    height, width = image.shape[:2]
    if max(height, width) < 800:
        scale = 800 / max(height, width)
        image = cv2.resize(image, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_CUBIC)

    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # Find all face locations in the image
    # number_of_times_to_upsample=1 helps detect smaller/farther faces
    face_locations = face_recognition.face_locations(
        rgb_image, model="hog", number_of_times_to_upsample=1
    )

    # If no face found, return None
    if not face_locations:
        return None

    # Get encoding for the first face found
    # face_encodings returns a list — we take the first one
    encodings = face_recognition.face_encodings(
        rgb_image, face_locations
    )

    if not encodings:
        return None

    return encodings[0]  # 128-number numpy array


# ---------------------------------------------------------------
# FUNCTION: load_image_from_bytes
# Converts raw bytes (received from browser) into a numpy array
# that OpenCV and face_recognition can work with.
# ---------------------------------------------------------------
def load_image_from_bytes(image_bytes: bytes) -> np.ndarray:
    np_arr = np.frombuffer(image_bytes, np.uint8)
    image  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    return image


# ---------------------------------------------------------------
# FUNCTION: load_image_from_path
# Loads an image from a file path on disk.
# We use this to load the saved ID card frame from uploads/.
# ---------------------------------------------------------------
def load_image_from_path(path: str) -> np.ndarray:
    image = cv2.imread(path)
    return image


# ---------------------------------------------------------------
# FUNCTION: match_faces
# Main function called by main.py.
#
# selfie_bytes  → raw bytes of the live camera frame (selfie)
# id_image_path → file path to the saved ID card image
#
# Returns a dict with:
#   matched      → True/False
#   distance     → how different the faces are (lower = more similar)
#   confidence   → human-readable confidence percentage
#   message      → result message for the UI
# ---------------------------------------------------------------
def match_faces(selfie_bytes: bytes, id_image_path: str) -> dict:

    # --- Step 1: Load selfie image ---
    selfie_image = load_image_from_bytes(selfie_bytes)
    if selfie_image is None:
        return {
            "matched":    False,
            "distance":   None,
            "confidence": None,
            "message":    "Could not decode selfie image"
        }

    # --- Step 2: Load ID card image from disk ---
    if not os.path.exists(id_image_path):
        return {
            "matched":    False,
            "distance":   None,
            "confidence": None,
            "message":    "ID card image not found — please scan ID first"
        }

    id_image = load_image_from_path(id_image_path)
    if id_image is None:
        return {
            "matched":    False,
            "distance":   None,
            "confidence": None,
            "message":    "Could not load ID card image"
        }

    # --- Step 3: Get face encoding from selfie ---
    selfie_encoding = get_face_encoding(selfie_image)
    if selfie_encoding is None:
        return {
            "matched":    False,
            "distance":   None,
            "confidence": None,
            "message":    "No face found in selfie — look directly at camera"
        }

    # --- Step 4: Get face encoding from ID card ---
    id_encoding = get_face_encoding(id_image)
    if id_encoding is None:
        return {
            "matched":    False,
            "distance":   None,
            "confidence": None,
            "message":    "No face found in ID card image — try rescanning"
        }

    # --- Step 5: Calculate distance between the two encodings ---
    # face_recognition.face_distance returns an array — we take [0]
    distance = face_recognition.face_distance(
        [id_encoding], selfie_encoding
    )[0]

    distance = float(round(distance, 4))

        # --- Step 6: Convert distance to confidence percentage ---
    #
    # Real-world face_recognition distances for the SAME person
    # typically fall between 0.0 (identical) and ~0.50.
    # Distances for DIFFERENT people are usually above 0.6.
    #
    # We map this range onto 0-100% so a genuine match shows a
    # realistic, high confidence number instead of a misleadingly
    # low one. This does NOT change whether something matches —
    # only how the confidence is displayed.
    #
    # GOOD_DISTANCE = distance at which we consider it a "perfect"
    # match (100% confidence) — a small buffer above 0 accounts
    # for natural lighting/angle variation between two real photos.
    GOOD_DISTANCE = 0.30

    if distance <= GOOD_DISTANCE:
        # Very close match — scale between 90% and 100%
        confidence = 100 - (distance / GOOD_DISTANCE) * 10
    else:
        # Between GOOD_DISTANCE and MATCH_THRESHOLD — scale 90% down to 0%
        remaining_range = MATCH_THRESHOLD - GOOD_DISTANCE
        distance_past_good = distance - GOOD_DISTANCE
        confidence = 90 * (1 - (distance_past_good / remaining_range))

    confidence = max(0, min(100, round(confidence, 1)))

    # --- Step 7: Determine match result ---
    matched = distance < MATCH_THRESHOLD

    print(f"Face match — distance: {distance}, "
          f"confidence: {confidence}%, matched: {matched}")

    return {
        "matched":    matched,
        "distance":   distance,
        "confidence": confidence,
        "message": (
            f"✓ Face matched! Confidence: {confidence}%"
            if matched else
            f"✗ Face did not match (confidence: {confidence}%)"
        )
    }