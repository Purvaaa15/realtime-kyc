# spoof_detector.py
# Anti-spoofing module — detects printed photos and screen replay attacks
# WITHOUT needing a pretrained deep learning model.
#
# HOW IT WORKS — three independent signals combined into one score:
#
# 1. TEXTURE ANALYSIS (Local Binary Patterns)
#    Real skin has fine, irregular texture (pores, tiny shadows).
#    A printed photo or screen shows the texture of PAPER or PIXELS
#    instead of skin — much more uniform and repetitive.
#
# 2. FREQUENCY DOMAIN ANALYSIS (FFT)
#    Every digital screen has a pixel grid. When you photograph a
#    screen, that grid creates a repeating pattern invisible to the
#    naked eye but very visible as sharp peaks in the frequency
#    domain (Fourier Transform). Real faces don't have this pattern.
#
# 3. SHARPNESS / BLUR ANALYSIS (Laplacian variance)
#    A photo of a photo (print attack) is very slightly softer/blurrier
#    than a real face captured directly, because you're photographing
#    a flat surface through an extra layer of reflection and paper grain.

import cv2
import numpy as np


# ---------------------------------------------------------------
# FUNCTION: compute_texture_score
# Uses Local Binary Patterns (LBP) to measure texture uniformity.
#
# LBP works by comparing each pixel to its 8 neighbours and encoding
# whether each neighbour is brighter or darker as a binary number.
# Real skin produces a wide, varied histogram of these patterns.
# Paper/screens produce a narrower, more repetitive histogram.
#
# We measure this "narrowness" using the histogram's entropy —
# low entropy = too uniform = likely fake
# high entropy = naturally varied = likely real skin
# ---------------------------------------------------------------
def compute_texture_score(face_region: np.ndarray) -> float:
    grey = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)

    # Compute a simplified LBP manually using pixel neighbour comparison
    height, width = grey.shape
    lbp = np.zeros((height - 2, width - 2), dtype=np.uint8)

    # Compare each pixel to its 8 surrounding neighbours
    # This loop is vectorised using numpy slicing (fast, no Python loop)
    center = grey[1:-1, 1:-1]
    neighbours = [
        grey[0:-2, 0:-2], grey[0:-2, 1:-1], grey[0:-2, 2:],
        grey[1:-1, 2:],   grey[2:, 2:],     grey[2:, 1:-1],
        grey[2:, 0:-2],   grey[1:-1, 0:-2],
    ]

    for i, n in enumerate(neighbours):
        lbp |= ((n >= center).astype(np.uint8)) << i

    # Build histogram of LBP values (0-255)
    hist, _ = np.histogram(lbp, bins=256, range=(0, 256))
    hist = hist.astype(np.float32)
    hist /= (hist.sum() + 1e-7)  # normalise to probabilities

    # Calculate entropy — higher entropy = more varied texture = more "real"
    entropy = -np.sum(hist * np.log2(hist + 1e-7))

    # Normalise entropy to a 0-1 "realness" score
    # Typical real face entropy: ~6.5-7.5 out of max 8
    # Typical print/screen entropy: ~4.5-6.0
    realness = np.clip((entropy - 4.0) / 3.5, 0, 1)

    return float(realness)


# ---------------------------------------------------------------
# FUNCTION: compute_frequency_score
# Detects screen replay attacks using FFT (Fast Fourier Transform).
#
# A photo of a screen has a repeating pixel-grid pattern that shows
# up as distinct bright spots in the frequency domain, away from
# the center. A real face's frequency spectrum is smoother and
# concentrated near the center (low frequencies = smooth gradients).
# ---------------------------------------------------------------
def compute_frequency_score(face_region: np.ndarray) -> float:
    grey = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
    grey = cv2.resize(grey, (256, 256))  # standard size for consistent analysis

    # Compute 2D FFT and shift zero-frequency to center
    f_transform = np.fft.fft2(grey)
    f_shift     = np.fft.fftshift(f_transform)
    magnitude   = np.abs(f_shift)

    # Convert to log scale (frequency magnitudes span huge ranges)
    magnitude_log = np.log(magnitude + 1)

    # Look at the OUTER RING of the frequency spectrum (high frequencies)
    # Screen replay attacks show unusually high energy here due to
    # the pixel grid pattern. Real faces have low energy here.
    h, w = magnitude_log.shape
    center_y, center_x = h // 2, w // 2

    # Create a mask for the outer 30% ring (high frequency band)
    y, x = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((y - center_y)**2 + (x - center_x)**2)
    max_dist = np.sqrt(center_y**2 + center_x**2)

    outer_ring_mask = dist_from_center > (max_dist * 0.7)

    outer_energy = magnitude_log[outer_ring_mask].mean()
    total_energy = magnitude_log.mean()

    # Ratio of high-frequency energy to total energy
    # High ratio = screen grid pattern present = likely spoof
    high_freq_ratio = outer_energy / (total_energy + 1e-7)

    # Normalise: typical real face ratio ~0.6-0.8
    #            typical screen replay ratio ~0.9-1.3
    realness = np.clip(1.4 - high_freq_ratio, 0, 1)

    return float(realness)


# ---------------------------------------------------------------
# FUNCTION: compute_sharpness_score
# Uses Laplacian variance to measure image sharpness.
# Very low sharpness can indicate a print attack (extra blur layer)
# or a low-quality replay. Very high uniform sharpness across a flat
# surface can also be a print-attack signal.
# ---------------------------------------------------------------
def compute_sharpness_score(face_region: np.ndarray) -> float:
    grey = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(grey, cv2.CV_64F)
    variance  = laplacian.var()
    # Recalibrated for typical webcam quality (was /300, too strict)
    realness = np.clip(variance / 120, 0, 1)
    return float(realness)


# ---------------------------------------------------------------
# FUNCTION: analyze_spoof
# Main function — combines all three signals into one spoof score.
#
# face_region: cropped face image (numpy array, BGR)
# Returns a dict with individual scores and a final verdict.
# ---------------------------------------------------------------
def analyze_spoof(face_region: np.ndarray, full_frame: np.ndarray = None) -> dict:
    if face_region is None or face_region.size == 0:
        return {
            "is_live":     False,
            "spoof_score": 0.0,
            "error":       "Empty face region"
        }

    texture_score   = compute_texture_score(face_region)
    frequency_score = compute_frequency_score(face_region)
    sharpness_score = compute_sharpness_score(face_region)

    # Bezel detection needs the FULL frame (not just the cropped face)
    # since the device edge is usually outside the face crop itself
    bezel_score = compute_bezel_score(full_frame) if full_frame is not None else 1.0

    # Weighted combination — bezel detection is now the strongest
    # signal since it catches what texture/frequency miss (a good
    # quality photo/video shown on a phone can fool texture analysis,
    # but the physical device edge is very hard to hide)
    combined_score = (
        texture_score   * 0.25 +
        frequency_score * 0.20 +
        sharpness_score * 0.05 +
        bezel_score      * 0.50
    )

    # Threshold: below 0.5 → likely spoof
    is_live = combined_score >= 0.5

    return {
        "is_live":         is_live,
        "spoof_score":     round(combined_score, 3),
        "texture_score":   round(texture_score, 3),
        "frequency_score": round(frequency_score, 3),
        "sharpness_score": round(sharpness_score, 3),
        "bezel_score":     round(bezel_score, 3),
        "message": (
            "✓ Live person detected" if is_live
            else "⚠️ Possible spoof detected — printed photo or screen replay"
        )
    }


# ---------------------------------------------------------------
# FUNCTION: extract_face_region
# Given a full frame and bounding box coordinates from MediaPipe
# landmarks, crops out just the face region for spoof analysis.
# ---------------------------------------------------------------
def extract_face_region(image: np.ndarray, landmarks: list) -> np.ndarray:
    if not landmarks:
        return None

    xs = [p["x"] for p in landmarks]
    ys = [p["y"] for p in landmarks]

    x_min, x_max = max(0, min(xs)), max(xs)
    y_min, y_max = max(0, min(ys)), max(ys)

    # Add a small margin around the face
    margin = int((x_max - x_min) * 0.1)
    x_min = max(0, x_min - margin)
    y_min = max(0, y_min - margin)
    x_max = min(image.shape[1], x_max + margin)
    y_max = min(image.shape[0], y_max + margin)

    face_region = image[y_min:y_max, x_min:x_max]
    return face_region

# ---------------------------------------------------------------
# FUNCTION: compute_bezel_score
# Detects whether a rectangular device bezel/edge is visible in
# the frame around the face — a strong signal of screen replay
# attacks (holding a phone/tablet/monitor up to the camera).
#
# HOW IT WORKS:
# A real face sits in open space with irregular, organic edges
# (hair, shoulders, background) around it. A phone screen has
# hard, perfectly straight rectangular edges (the physical bezel)
# somewhere in the frame. We use Canny edge detection + Hough Line
# Transform to look for long, straight lines — something a real
# face+background scene rarely produces, but a device edge always does.
# ---------------------------------------------------------------
def compute_bezel_score(full_frame: np.ndarray) -> float:
    grey = cv2.cvtColor(full_frame, cv2.COLOR_BGR2GRAY)

    # Detect edges
    edges = cv2.Canny(grey, 50, 150)

    # Detect straight lines using Hough Transform
    # minLineLength: a line must be at least this long (in pixels)
    #                to count — filters out short, noisy edges
    # maxLineGap: allow small gaps in a line (e.g. from lighting)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=80,
        minLineLength=int(full_frame.shape[0] * 0.3),
        maxLineGap=10
    )

    if lines is None:
        return 1.0  # no long straight lines found — likely real, open scene

    # Count how many detected lines are close to perfectly
    # horizontal or vertical (device bezels are always axis-aligned
    # when someone holds a phone up naturally)
    straight_axis_aligned_count = 0
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        angle = abs(angle) % 180

        # Close to 0° (horizontal) or 90° (vertical)
        if angle < 5 or angle > 175 or (85 < angle < 95):
            straight_axis_aligned_count += 1

    # Many axis-aligned straight lines = likely a device bezel present
    # Normalise: 0 lines = 1.0 (real), 6+ lines = 0.0 (likely spoof)
    realness = np.clip(1.0 - (straight_axis_aligned_count / 6), 0, 1)

    return float(realness)

