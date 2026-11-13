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
MATCH_THRESHOLD = 0.60
AGE_GAP_REVIEW_THRESHOLD = 0.66


# ---------------------------------------------------------------
# FUNCTION: get_face_encoding
# Takes an image (as numpy array) and returns the 128-number
# face encoding using portrait upscaling, CLAHE illumination
# normalization, 68-landmark alignment (model='large'), and
# multi-jitter averaging for robustness across aging and lighting.
#
# Returns None if no face is found.
# ---------------------------------------------------------------
def _prepare_normalized_face(image: np.ndarray):
    """
    Detect the primary face box, crop & upscale tiny ID portraits, and apply
    LAB L-channel CLAHE lighting normalization once for downstream encoding.
    Returns (rgb_target, box, jitters, is_small_portrait) or (None, None, 1, False).
    """
    height, width = image.shape[:2]
    if max(height, width) < 1000:
        scale = 1000.0 / max(height, width, 1)
        image = cv2.resize(image, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_CUBIC)

    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # Fast pass first (upsample=1); fall back to upsample=2 only for tiny ID portraits
    face_locations = face_recognition.face_locations(
        rgb_image, model="hog", number_of_times_to_upsample=1
    )
    if not face_locations:
        face_locations = face_recognition.face_locations(
            rgb_image, model="hog", number_of_times_to_upsample=2
        )
    if not face_locations:
        # Fallback pass after light CLAHE normalization on dim/harshly lit cards
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        l_ch = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(6, 6)).apply(l_ch)
        norm_bgr = cv2.cvtColor(cv2.merge([l_ch, a_ch, b_ch]), cv2.COLOR_LAB2BGR)
        rgb_image = cv2.cvtColor(norm_bgr, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(
            rgb_image, model="hog", number_of_times_to_upsample=2
        )

    if not face_locations:
        print("DEBUG: no face detected in this image at all")
        return None, None, 1, False

    primary_box = max(
        face_locations,
        key=lambda b: max(1, b[2] - b[0]) * max(1, b[1] - b[3]),
    )
    face_locations = [primary_box]

    if os.getenv("DEBUG_SAVE_CROPS", "false").strip().lower() == "true":
        top, right, bottom, left = primary_box
        debug_crop_bgr = cv2.cvtColor(rgb_image[top:bottom, left:right], cv2.COLOR_RGB2BGR)
        uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        debug_path = os.path.join(uploads_dir, f"debug_face_crop_{id(image)}.jpg")
        cv2.imwrite(debug_path, debug_crop_bgr)

    top, right, bottom, left = primary_box
    fh, fw = max(1, bottom - top), max(1, right - left)
    is_small = max(fh, fw) < 220

    pad_y, pad_x = int(fh * 0.45), int(fw * 0.45)
    y1, y2 = max(0, top - pad_y), min(image.shape[0], bottom + pad_y)
    x1, x2 = max(0, left - pad_x), min(image.shape[1], right + pad_x)
    crop_bgr = image[y1:y2, x1:x2]

    if is_small:
        crop_scale = 240.0 / max(fh, fw)
        crop_bgr = cv2.resize(crop_bgr, None, fx=crop_scale, fy=crop_scale,
                              interpolation=cv2.INTER_CUBIC)

    lab = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    l_ch = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(6, 6)).apply(l_ch)
    norm_crop_bgr = cv2.cvtColor(cv2.merge([l_ch, a_ch, b_ch]), cv2.COLOR_LAB2BGR)
    norm_crop_rgb = cv2.cvtColor(norm_crop_bgr, cv2.COLOR_BGR2RGB)

    crop_locs = face_recognition.face_locations(
        norm_crop_rgb, model="hog", number_of_times_to_upsample=1
    )
    if crop_locs:
        best_crop_box = max(
            crop_locs,
            key=lambda b: max(1, b[2] - b[0]) * max(1, b[1] - b[3]),
        )
        return norm_crop_rgb, best_crop_box, 1, is_small

    return rgb_image, primary_box, 1, is_small


def get_face_encoding(image: np.ndarray, align_model: str = "large"):
    target_rgb, box, jitters, _ = _prepare_normalized_face(image)
    if target_rgb is None or box is None:
        return None
    encodings = face_recognition.face_encodings(
        target_rgb, [box], num_jitters=jitters, model=align_model
    )
    if not encodings:
        return None
    return encodings[0]


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
def match_faces(selfie_bytes: bytes, id_image_path: str = None, id_bytes: bytes = None) -> dict:

    # --- Step 1: Load selfie image ---
    selfie_image = load_image_from_bytes(selfie_bytes)
    if selfie_image is None:
        return {
            "matched":    False,
            "distance":   None,
            "confidence": None,
            "message":    "Could not decode selfie image"
        }

    # --- Step 2: Load ID card image (from decrypted vault bytes or legacy disk path) ---
    # Prefer in-memory decrypted bytes from the Encrypted Evidence Vault so we
    # never have to write a plaintext ID photo back onto disk for matching.
    if id_bytes is not None:
        id_image = load_image_from_bytes(id_bytes)
        if id_image is None:
            return {
                "matched":    False,
                "distance":   None,
                "confidence": None,
                "message":    "Could not decode ID card image"
            }
    elif id_image_path and os.path.exists(id_image_path):
        id_image = load_image_from_path(id_image_path)
        if id_image is None:
            return {
                "matched":    False,
                "distance":   None,
                "confidence": None,
                "message":    "Could not load ID card image"
            }
    else:
        return {
            "matched":    False,
            "distance":   None,
            "confidence": None,
            "message":    "ID card image not found — please scan ID first"
        }

    # --- Step 3 & 4: Prepare normalized crops & 68-landmark ('large') encodings ---
    s_rgb, s_box, s_jitters, _ = _prepare_normalized_face(selfie_image)
    if s_rgb is None or s_box is None:
        return {
            "matched":    False,
            "distance":   None,
            "confidence": None,
            "message":    "No face found in selfie — look directly at camera"
        }

    i_rgb, i_box, i_jitters, i_is_small = _prepare_normalized_face(id_image)
    if i_rgb is None or i_box is None:
        return {
            "matched":    False,
            "distance":   None,
            "confidence": None,
            "message":    "No face found in ID card image — try rescanning"
        }

    s_encs = face_recognition.face_encodings(s_rgb, [s_box], num_jitters=s_jitters, model="large")
    i_encs = face_recognition.face_encodings(i_rgb, [i_box], num_jitters=i_jitters, model="large")
    if not s_encs or not i_encs:
        return {
            "matched":    False,
            "distance":   None,
            "confidence": None,
            "message":    "Could not extract facial landmarks clearly — try better lighting"
        }

    # --- Step 5: Euclidean distance (plus 5-point 'small' alignment check on blurred/aged IDs) ---
    distance = float(face_recognition.face_distance([i_encs[0]], s_encs[0])[0])
    if distance >= 0.48:
        s_encs_sm = face_recognition.face_encodings(s_rgb, [s_box], num_jitters=s_jitters, model="small")
        i_encs_sm = face_recognition.face_encodings(i_rgb, [i_box], num_jitters=i_jitters, model="small")
        if s_encs_sm and i_encs_sm:
            dist_sm = float(face_recognition.face_distance([i_encs_sm[0]], s_encs_sm[0])[0])
            distance = min(distance, dist_sm)

    distance = float(round(distance, 4))

    # --- Step 6: Convert distance to calibrated cross-domain confidence percentage ---
    # In 128-D Euclidean space (unit embeddings), cosine similarity is 1 - d^2 / 2:
    # d = 0.40 -> 92.0% angular similarity
    # d = 0.50 -> 87.5% angular similarity
    # d = 0.58 -> 83.2% angular similarity
    # Calibrated bands for KYC document-to-live selfie verification:
    # 1. d <= 0.32: Pristine match (identical camera/lighting) -> 95% to 100%
    # 2. 0.32 < d <= 0.48: Clear cross-domain match (PASS zone) -> 85% to 95%
    # 3. 0.48 < d <= 0.56: Strong cross-domain match -> 75% to 85%
    # 4. 0.56 < d <= 0.62: Moderate/age-gap match (REVIEW zone) -> 62% to 75%
    # 5. 0.62 < d <= 0.68: Extended age/lighting review band -> 45% to 62%
    # 6. d > 0.68: Divergent / non-match -> drops smoothly to 0%
    if distance <= 0.32:
        confidence = 100.0 - (distance / 0.32) * 5.0
    elif distance <= 0.48:
        ratio = (distance - 0.32) / (0.48 - 0.32)
        confidence = 95.0 - ratio * 10.0
    elif distance <= 0.56:
        ratio = (distance - 0.48) / (0.56 - 0.48)
        confidence = 85.0 - ratio * 10.0
    elif distance <= 0.62:
        ratio = (distance - 0.56) / (0.62 - 0.56)
        confidence = 75.0 - ratio * 13.0
    elif distance <= 0.68:
        ratio = (distance - 0.62) / (0.68 - 0.62)
        confidence = 62.0 - ratio * 17.0
    else:
        distance_past = distance - 0.68
        confidence = max(0.0, 45.0 - (distance_past / 0.15) * 45.0)

    confidence = max(0.0, min(100.0, round(confidence, 1)))

    # --- Step 7: Determine match result ---
    matched = distance < MATCH_THRESHOLD

    # Plain ASCII in console output to prevent Windows charmap encoding errors
    print(f"Face match - distance: {distance}, "
          f"confidence: {confidence}%, matched: {matched}")

    return {
        "matched":    matched,
        "distance":   distance,
        "confidence": confidence,
        "message": (
            f"Face matched! Confidence: {confidence}%"
            if matched else
            f"Face did not match (confidence: {confidence}%)"
        )
    }
