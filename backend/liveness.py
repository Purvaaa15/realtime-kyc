# liveness.py
# This module detects whether the user is a live person by tracking blinks.
#
# HOW IT WORKS:
# We look at 4 specific landmark points around each eye:
#   - top point (eyelid top)
#   - bottom point (eyelid bottom)
#   - left corner
#   - right corner
#
# Eye Aspect Ratio (EAR) = vertical distance / horizontal distance
#
# Eye OPEN  → EAR is roughly 0.25 to 0.35
# Eye CLOSED → EAR drops below 0.20
#
# If EAR drops below threshold and comes back up = 1 blink detected.
# We require 2 blinks to pass liveness.

import math

# ---------------------------------------------------------------
# EAR THRESHOLD: if EAR drops below this, eye is considered closed
# EAR_CONSEC_FRAMES: eye must be closed for this many frames
#                    (avoids false positives from a single bad frame)
# BLINKS_REQUIRED: how many blinks needed to pass liveness
# ---------------------------------------------------------------
EAR_THRESHOLD    = 0.20
EAR_CONSEC_FRAMES = 2
BLINKS_REQUIRED  = 2


# ---------------------------------------------------------------
# FUNCTION: euclidean_distance
# Calculates straight-line distance between two (x, y) points.
# This is basic geometry: sqrt((x2-x1)² + (y2-y1)²)
# We use this to measure distances between eye landmark points.
# ---------------------------------------------------------------
def euclidean_distance(point1: dict, point2: dict) -> float:
    return math.sqrt(
        (point2["x"] - point1["x"]) ** 2 +
        (point2["y"] - point1["y"]) ** 2
    )


# ---------------------------------------------------------------
# FUNCTION: calculate_ear
# Calculates the Eye Aspect Ratio for one eye.
#
# We use 4 points from the eye landmarks:
#   points[0] = top of eyelid
#   points[1] = bottom of eyelid
#   points[2] = left corner of eye
#   points[3] = right corner of eye
#
# EAR = vertical_distance / horizontal_distance
#
# When eye is open: vertical is large, EAR is high (~0.3)
# When eye is closed: vertical is tiny, EAR is low (~0.05)
# ---------------------------------------------------------------
def calculate_ear(eye_points: list) -> float:
    # eye_points come from LEFT_EYE_EAR_POINTS or RIGHT_EYE_EAR_POINTS
    # defined in face_detector.py as [top, bottom, left, right]
    top    = eye_points[0]
    bottom = eye_points[1]
    left   = eye_points[2]
    right  = eye_points[3]

    vertical   = euclidean_distance(top, bottom)
    horizontal = euclidean_distance(left, right)

    # Avoid division by zero (just in case)
    if horizontal == 0:
        return 0.0

    ear = vertical / horizontal
    return ear


# ---------------------------------------------------------------
# CLASS: LivenessChecker
# Keeps track of blink state across multiple frames.
#
# Why a class? Because we need to REMEMBER state between frames:
#   - how many frames has the eye been closed?
#   - how many blinks have happened so far?
# A class lets us store this memory as instance variables.
# ---------------------------------------------------------------
class LivenessChecker:
    def __init__(self):
        # How many consecutive frames the eye has been below threshold
        self.frame_counter = 0

        # Total blinks detected so far in this session
        self.blink_count = 0

        # Whether liveness has been confirmed
        self.passed = False

        # EAR history for the last few frames (useful for debugging)
        self.ear_history = []


    # ---------------------------------------------------------------
    # METHOD: process_frame
    # Called once per frame with the landmark data from face_detector.
    # Updates blink count and returns current liveness status.
    #
    # landmarks: the full list of 468 face landmarks [{x, y}, ...]
    # ear_points_left:  4 specific eye points for left eye
    # ear_points_right: 4 specific eye points for right eye
    # ---------------------------------------------------------------
    def process_frame(self, landmarks: list,
                      ear_points_left: list,
                      ear_points_right: list) -> dict:

        # If already passed, no need to keep checking
        if self.passed:
            return self._status()

        # Step 1: Calculate EAR for both eyes
        ear_left  = calculate_ear(ear_points_left)
        ear_right = calculate_ear(ear_points_right)

        # Average both eyes — more reliable than just one
        ear_avg = (ear_left + ear_right) / 2.0

        # Keep a small history (last 10 values) for debugging
        self.ear_history.append(round(ear_avg, 3))
        if len(self.ear_history) > 10:
            self.ear_history.pop(0)

        # Step 2: Check if eyes are closed (EAR below threshold)
        if ear_avg < EAR_THRESHOLD:
            # Eyes appear closed — increment the frame counter
            self.frame_counter += 1

        else:
            # Eyes are open again
            # If they were closed for enough consecutive frames → blink!
            if self.frame_counter >= EAR_CONSEC_FRAMES:
                self.blink_count += 1
                print(f"Blink detected! Total blinks: {self.blink_count}")

            # Reset the frame counter for next blink
            self.frame_counter = 0

        # Step 3: Check if we've reached the required number of blinks
        if self.blink_count >= BLINKS_REQUIRED:
            self.passed = True

        return self._status()


    # ---------------------------------------------------------------
    # METHOD: _status
    # Returns the current liveness state as a dictionary.
    # The underscore prefix means this is an "internal" helper method.
    # ---------------------------------------------------------------
    def _status(self) -> dict:
        return {
            "liveness_passed": self.passed,
            "blink_count":     self.blink_count,
            "blinks_required": BLINKS_REQUIRED,
            "message": (
                "✓ Liveness confirmed!" if self.passed
                else f"Please blink naturally — {self.blink_count}/{BLINKS_REQUIRED} blinks detected"
            )
        }


    # ---------------------------------------------------------------
    # METHOD: reset
    # Resets the checker for a new session.
    # ---------------------------------------------------------------
    def reset(self):
        self.frame_counter = 0
        self.blink_count   = 0
        self.passed        = False
        self.ear_history   = []