# evaluate.py
# Standalone evaluation & latency benchmark script for PehchaanAI.
#
# PURPOSE:
# Measures empirical latency (ms per pipeline stage) and face-matching
# score distribution across saved session pairs in uploads/.
# Use the output numbers directly in your VIT Review 1 / Review 2 reports!
#
# HOW TO RUN (from project root):
#   venv\Scripts\python.exe backend\evaluate.py

import os
import sys
import time
import glob
import statistics
import cv2

# Ensure UTF-8 printing works safely in Windows terminals
sys.stdout.reconfigure(encoding="utf-8")

# Allow importing backend modules cleanly regardless of working directory
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BACKEND_DIR, "..", "uploads")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from face_detector import detect_face
from spoof_detector import analyze_spoof, extract_face_region
from ocr import scan_document
from face_match import match_faces
from decision import make_decision
from database import get_dashboard_analytics


def run_evaluation():
    print("=" * 65)
    print("   PehchaanAI — Pipeline Evaluation & Latency Benchmark")
    print("=" * 65)

    # 1. Find all saved session pairs (id_<sid>.jpg and selfie_<sid>.jpg)
    selfie_files = sorted(glob.glob(os.path.join(UPLOADS_DIR, "selfie_*.jpg")))
    pairs = []
    for s_path in selfie_files:
        basename = os.path.basename(s_path)
        if basename == "selfie_frame.jpg":
            continue
        sid = basename.replace("selfie_", "").replace(".jpg", "")
        id_path = os.path.join(UPLOADS_DIR, f"id_{sid}.jpg")
        if os.path.exists(id_path):
            pairs.append((sid, s_path, id_path))

    print(f"\nFound {len(pairs)} paired (selfie + ID) sessions in uploads/.\n")

    if not pairs:
        print("No session pairs found to evaluate.")
        return

    face_latencies = []
    spoof_latencies = []
    match_latencies = []
    ocr_latencies = []

    distances = []
    confidences = []
    verdict_counts = {"PASS": 0, "REVIEW": 0, "FAIL": 0}
    ocr_success_count = 0

    print(f"{'Session':<10} | {'Dist':<7} | {'Conf %':<7} | {'Verdict':<7} | {'Match ms':<9} | {'OCR Status'}")
    print("-" * 65)

    for sid, s_path, id_path in pairs:
        with open(s_path, "rb") as f:
            selfie_bytes = f.read()
        with open(id_path, "rb") as f:
            id_bytes = f.read()

        # --- Measure Face Detection latency ---
        t0 = time.perf_counter()
        face_res = detect_face(selfie_bytes)
        face_ms = (time.perf_counter() - t0) * 1000
        face_latencies.append(face_ms)

        # --- Measure Anti-Spoofing latency ---
        if face_res.get("face_found"):
            img = cv2.imread(s_path)
            crop = extract_face_region(img, face_res["landmarks"])
            t0 = time.perf_counter()
            analyze_spoof(crop, full_frame=img)
            spoof_ms = (time.perf_counter() - t0) * 1000
            spoof_latencies.append(spoof_ms)

        # --- Measure Face Matching latency & accuracy ---
        t0 = time.perf_counter()
        match_res = match_faces(selfie_bytes, id_path)
        match_ms = (time.perf_counter() - t0) * 1000
        match_latencies.append(match_ms)

        # --- Measure OCR latency on unique/selected ID uploads ---
        # Run OCR on each card to measure quality gate pass rate & latency
        t0 = time.perf_counter()
        ocr_res = scan_document(id_bytes)
        ocr_ms = (time.perf_counter() - t0) * 1000
        ocr_latencies.append(ocr_ms)
        if ocr_res.get("success"):
            ocr_success_count += 1

        dist = match_res.get("distance")
        conf = match_res.get("confidence")
        matched = match_res.get("matched", False)

        if dist is not None and conf is not None:
            distances.append(dist)
            confidences.append(conf)
            dec = make_decision(
                face_found=True,
                liveness_passed=True,
                id_scanned=True,
                face_matched=matched,
                match_confidence=conf,
                id_fields=ocr_res.get("fields", {}),
                spoof_detected=False,
                match_distance=dist,
            )
            verdict = dec["verdict"]
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            ocr_status = "OK" if ocr_res.get("success") else "Rejected"
            print(f"{sid:<10} | {dist:<7.4f} | {conf:<7.1f} | {verdict:<7} | {match_ms:<9.1f} | {ocr_status}")
        else:
            print(f"{sid:<10} | {'N/A':<7} | {'N/A':<7} | {'FAIL':<7} | {match_ms:<9.1f} | {match_res.get('message')}")

    # 2. Print Summary Report
    print("\n" + "=" * 65)
    print("   1. PER-STAGE LATENCY SUMMARY (CPU)")
    print("=" * 65)
    for name, vals in [
        ("MediaPipe FaceMesh (detect_face)", face_latencies),
        ("Anti-Spoofing (analyze_spoof)", spoof_latencies),
        ("Face Matching (dlib 128-d)", match_latencies),
        ("Document OCR (Tesseract)", ocr_latencies),
    ]:
        if vals:
            print(
                f"{name:<36} | avg: {statistics.mean(vals):6.1f} ms | "
                f"min: {min(vals):6.1f} ms | max: {max(vals):6.1f} ms"
            )

    print("\n" + "=" * 65)
    print("   2. GENUINE FACE-MATCH DISTRIBUTION (SAME PERSON PAIRS)")
    print("=" * 65)
    if distances:
        print(f"Total evaluated genuine pairs : {len(distances)}")
        print(f"Distance range                : {min(distances):.4f} – {max(distances):.4f}")
        print(f"Mean / Median distance        : {statistics.mean(distances):.4f} / {statistics.median(distances):.4f}")
        print(f"Mean / Median confidence      : {statistics.mean(confidences):.1f}% / {statistics.median(confidences):.1f}%")
        print(f"Verdict distribution          : PASS={verdict_counts['PASS']}, REVIEW={verdict_counts['REVIEW']}, FAIL={verdict_counts['FAIL']}")
        frr = (verdict_counts["FAIL"] / len(distances)) * 100
        print(f"False Rejection Rate (FRR)    : {frr:.1f}% (0% if FAIL=0)")
    print(f"OCR Quality Gate Pass Rate    : {ocr_success_count}/{len(pairs)} ({(ocr_success_count/len(pairs)*100):.1f}%)")

    print("\n" + "=" * 65)
    print("   3. DATABASE OPERATIONAL ANALYTICS (POSTGRESQL)")
    print("=" * 65)
    try:
        analytics = get_dashboard_analytics()
        print(f"Total recorded sessions       : {analytics['total']}")
        print(f"Average session duration      : {analytics['avg_duration_sec']} seconds")
        print(f"Recorded spoof-flagged count  : {analytics['spoof_flagged']}")
    except Exception as e:
        print(f"Could not query PostgreSQL analytics: {e}")

    print("\n" + "=" * 65)
    print("   4. MULTI-SUBJECT IMPOSTOR CROSS-PAIR BENCHMARK (FAR)")
    print("=" * 65)
    subjects_dir = os.path.join(UPLOADS_DIR, "subjects")
    subject_samples = []
    if os.path.isdir(subjects_dir):
        for name in sorted(os.listdir(subjects_dir)):
            person_dir = os.path.join(subjects_dir, name)
            if not os.path.isdir(person_dir):
                continue
            selfies = sorted(
                p for ext in ("*.jpg", "*.jpeg", "*.png")
                for p in glob.glob(os.path.join(person_dir, f"selfie{ext[1:]}"))
            )
            ids = sorted(
                p for ext in ("*.jpg", "*.jpeg", "*.png")
                for p in glob.glob(os.path.join(person_dir, f"id{ext[1:]}"))
            )
            if selfies and ids:
                subject_samples.append((name, selfies[0], ids[0]))

    if len(subject_samples) < 2:
        print("Skipped: Fewer than 2 distinct subjects found in uploads/subjects/.")
        print("To measure empirical False Acceptance Rate (FAR) with your group mates:")
        print("  1. Create uploads/subjects/<teammate_name>/ (ignored by git)")
        print("  2. Add one selfie.jpg and one id.jpg per teammate (2+ teammates)")
        print("  3. Re-run: venv\\Scripts\\python.exe backend\\evaluate.py")
    else:
        impostor_distances = []
        false_accepts = 0
        print(f"Found {len(subject_samples)} distinct subjects: {', '.join(s[0] for s in subject_samples)}")
        print(f"{'Selfie Subject':<18} | {'ID Subject':<18} | {'Dist':<7} | {'Matched?'}")
        print("-" * 65)
        for s_name, s_path, _ in subject_samples:
            with open(s_path, "rb") as f:
                s_bytes = f.read()
            for id_name, _, id_path in subject_samples:
                if s_name == id_name:
                    continue
                res = match_faces(s_bytes, id_path)
                dist = res.get("distance")
                matched = bool(res.get("matched", False))
                if dist is not None:
                    impostor_distances.append(dist)
                if matched:
                    false_accepts += 1
                dist_str = f"{dist:.4f}" if dist is not None else "N/A"
                print(f"{s_name:<18} | {id_name:<18} | {dist_str:<7} | {'FAIL (Accepted)' if matched else 'Rejected'}")

        total_imp = len(subject_samples) * (len(subject_samples) - 1)
        far = (false_accepts / total_imp) * 100 if total_imp else 0.0
        if impostor_distances:
            print(f"\nImpostor pairs evaluated      : {total_imp}")
            print(f"Impostor distance range       : {min(impostor_distances):.4f} – {max(impostor_distances):.4f}")
            print(f"Mean impostor distance        : {statistics.mean(impostor_distances):.4f}")
        print(f"False Acceptance Rate (FAR)   : {far:.1f}% ({false_accepts}/{total_imp} matched < 0.60)")
    print("=" * 65)


if __name__ == "__main__":
    run_evaluation()
