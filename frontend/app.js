// app.js — Version 2.0
// Now uses:
//   - Session IDs (each user gets their own UUID)
//   - WebSocket for real-time frame streaming (lower latency)
//   - Falls back to REST API for ID scan and face match

const video      = document.getElementById("video");
const overlay    = document.getElementById("overlay");
const statusDot  = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");

const captureCanvas = document.createElement("canvas");
const captureCtx    = captureCanvas.getContext("2d");

const SERVER_URL = "http://localhost:8000";
const WS_URL     = "ws://localhost:8000";

// ---------------------------------------------------------------
// SESSION STATE
// ---------------------------------------------------------------
let sessionId       = null;   // UUID from server
let socket          = null;   // WebSocket connection
let livenessCleared = false;
let idScanned       = false;
let faceMatched     = false;
let sessionDone     = false;


// ---------------------------------------------------------------
// UI HELPERS
// ---------------------------------------------------------------
function setStatus(message, state = "ready") {
  statusText.textContent = message;
  statusDot.className    = "status-dot " + state;
}

function completeStep(stepNumber) {
  const step = document.getElementById("step" + stepNumber);
  if (step) step.classList.add("complete");
}

function showResult(passed, message) {
  const card  = document.getElementById("resultCard");
  const title = document.getElementById("resultTitle");
  const msg   = document.getElementById("resultMessage");

  card.style.display = "block";
  card.className     = "result-card " + (passed ? "pass" : "fail");
  title.textContent  = passed ? "✅ Verification Passed" : "❌ Verification Failed";
  msg.textContent    = message;
  card.scrollIntoView({ behavior: "smooth" });
}


// ---------------------------------------------------------------
// FUNCTION: initSession
// Calls /session/start to get a UUID from the server.
// This must happen before anything else.
// ---------------------------------------------------------------
async function initSession() {
  try {
    const response = await fetch(`${SERVER_URL}/session/start`, {
      method: "POST",
    });
    const data = await response.json();
    sessionId  = data.session_id;
    console.log("Session started:", sessionId);
    return true;
  } catch (error) {
    setStatus("Cannot reach server — is it running?", "error");
    console.error("Session init error:", error);
    return false;
  }
}


// ---------------------------------------------------------------
// FUNCTION: startCamera
// ---------------------------------------------------------------
async function startCamera() {
  try {
    setStatus("Requesting camera access...", "processing");

    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
      audio: false
    });

    video.srcObject = stream;

    await new Promise((resolve) => {
      video.onloadedmetadata = () => { video.play(); resolve(); };
    });

    overlay.width        = video.videoWidth;
    overlay.height       = video.videoHeight;
    captureCanvas.width  = video.videoWidth;
    captureCanvas.height = video.videoHeight;

    document.getElementById("liveBadge").style.display = "block";
    setStatus("Camera ready — look at the camera and blink twice", "ready");

  } catch (error) {
    setStatus("Camera access denied: " + error.message, "error");
    console.error("Camera error:", error);
  }
}


// ---------------------------------------------------------------
// FUNCTION: captureFrame
// ---------------------------------------------------------------
function captureFrame() {
  captureCtx.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);
  return new Promise((resolve) => {
    captureCanvas.toBlob(resolve, "image/jpeg", 0.85);
  });
}


// ---------------------------------------------------------------
// FUNCTION: captureFrameAsBase64
// For WebSocket — sends image as base64 string instead of Blob
// ---------------------------------------------------------------
function captureFrameAsBase64() {
  captureCtx.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);
  return captureCanvas.toDataURL("image/jpeg", 0.85);
}


// ---------------------------------------------------------------
// FUNCTION: drawLandmarks
// ---------------------------------------------------------------
function drawLandmarks(landmarks, imageWidth, imageHeight) {
  const ctx    = overlay.getContext("2d");
  ctx.clearRect(0, 0, overlay.width, overlay.height);

  const scaleX = overlay.width  / imageWidth;
  const scaleY = overlay.height / imageHeight;

  landmarks.forEach((point) => {
    ctx.beginPath();
    ctx.arc(point.x * scaleX, point.y * scaleY, 1.5, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(34, 197, 94, 0.8)";
    ctx.fill();
  });
}


// ---------------------------------------------------------------
// FUNCTION: openWebSocket
// Opens a persistent WebSocket connection to the server.
// Sends frames continuously and handles responses.
// ---------------------------------------------------------------
function openWebSocket() {
  if (!sessionId) return;

  // Open WebSocket connection to our session-specific endpoint
  socket = new WebSocket(`${WS_URL}/ws/${sessionId}`);

  socket.onopen = () => {
    console.log("WebSocket connected");
    setStatus("Connected — look at the camera and blink twice", "ready");

    // Start sending frames every 500ms via WebSocket
    // (faster than the old 1000ms REST polling)
    window.wsInterval = setInterval(sendFrameViaWebSocket, 500);
  };

  socket.onmessage = (event) => {
    // Handle response from server
    const data = JSON.parse(event.data);
    handleFrameResponse(data);
  };

  socket.onerror = (error) => {
    console.error("WebSocket error:", error);
    setStatus("Connection error — falling back to REST", "error");
  };

  socket.onclose = () => {
    console.log("WebSocket closed");
    clearInterval(window.wsInterval);
  };
}


// ---------------------------------------------------------------
// FUNCTION: sendFrameViaWebSocket
// Captures a frame and sends it through the WebSocket.
// Much faster than creating a new HTTP connection each time.
// ---------------------------------------------------------------
function sendFrameViaWebSocket() {
  if (sessionDone || !socket || socket.readyState !== WebSocket.OPEN) return;

  const base64Frame = captureFrameAsBase64();

  socket.send(JSON.stringify({
    type: "frame",
    data: base64Frame,
  }));
}


// ---------------------------------------------------------------
// FUNCTION: handleFrameResponse
// Processes the result from the server (same for WS and REST).
// ---------------------------------------------------------------
function handleFrameResponse(data) {
  if (sessionDone) return;

  if (data.error) {
    setStatus(data.error, "error");
    return;
  }

  if (data.face_found) {
    drawLandmarks(data.landmarks, data.width, data.height);
    completeStep(1);

    if (data.liveness.liveness_passed) {
      completeStep(2);

      if (!livenessCleared) {
        livenessCleared = true;
        showUploadSection();
      }

    } else {
      setStatus(data.liveness.message, "processing");
    }

  } else {
    const ctx = overlay.getContext("2d");
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    setStatus("No face detected — centre your face in the frame", "processing");
  }

      // Show spoof detection status (informational, doesn't block flow)
    if (data.spoof && !data.spoof.is_live) {
      console.warn("Spoof warning:", data.spoof);
    }

    if (data.liveness.liveness_passed) {
      completeStep(2);
  }    
}


// ---------------------------------------------------------------
// FUNCTION: showUploadSection
// Called once liveness passes. Reveals the file upload box
// and wires up the file input change event.
// ---------------------------------------------------------------
function showUploadSection() {
  const uploadSection = document.getElementById("uploadSection");
  const fileInput      = document.getElementById("idFileInput");

  uploadSection.style.display = "block";
  setStatus("📄 Please upload a photo of your ID card", "processing");

  // Listen for file selection (only wire this once)
  if (!fileInput.dataset.wired) {
    fileInput.dataset.wired = "true";
    fileInput.addEventListener("change", handleFileSelected);
  }
}


// ---------------------------------------------------------------
// FUNCTION: handleFileSelected
// Runs when the user picks a file from their device.
// Shows a preview, then uploads it to the server for OCR.
// ---------------------------------------------------------------
async function handleFileSelected(event) {
  const file = event.target.files[0];
  if (!file) return;

  // Validate file size (max 10MB)
  const maxSizeBytes = 10 * 1024 * 1024;
  if (file.size > maxSizeBytes) {
    setStatus("File too large — please choose a file under 10MB", "error");
    return;
  }

  // Show preview (only works for images, not PDFs)
  const previewBox   = document.getElementById("uploadPreview");
  const previewImage  = document.getElementById("previewImage");
  const previewName   = document.getElementById("previewFilename");
  const uploadBox     = document.getElementById("uploadBox");

  if (file.type.startsWith("image/")) {
    previewImage.src = URL.createObjectURL(file);
    previewImage.style.display = "block";
  } else {
    // PDF — no thumbnail, just show a document icon
    previewImage.style.display = "none";
  }

  previewName.textContent = file.name;
  previewBox.style.display = "flex";
  uploadBox.style.display  = "none";

  // Upload to server
  await uploadIDDocument(file);
}


// ---------------------------------------------------------------
// FUNCTION: uploadIDDocument
// Sends the selected file to /scan-id for OCR processing.
// ---------------------------------------------------------------
async function uploadIDDocument(file) {
  if (idScanned) return;

  try {
    setStatus("📤 Uploading and scanning your ID...", "processing");

    const formData = new FormData();
    formData.append("frame",      file, file.name);
    formData.append("session_id", sessionId);

    const response = await fetch(`${SERVER_URL}/scan-id`, {
      method: "POST",
      body: formData,
    });

    const data = await response.json();

    if (data.success) {
      idScanned = true;
      completeStep(3);

      const name = data.fields?.name || "detected";
      setStatus(`✓ ID verified — ${name}`, "ready");
      window.scannedIDFields = data.fields;

      // Hide upload section, move to face matching
      document.getElementById("uploadSection").style.display = "none";
      setTimeout(() => matchFaceToID(), 1500);

    } else {
      setStatus(`Scan failed — ${data.error}. Please try a clearer photo.`, "error");

      // Allow retry — reset the upload box
      setTimeout(() => {
        document.getElementById("uploadPreview").style.display = "none";
        document.getElementById("uploadBox").style.display     = "flex";
        document.getElementById("idFileInput").value            = "";
      }, 2500);
    }

  } catch (error) {
    setStatus("Upload error — is the server running?", "error");
    console.error("Upload error:", error);
  }
}


// ---------------------------------------------------------------
// FUNCTION: matchFaceToID
// Sends selfie via REST for face matching + final verdict
// ---------------------------------------------------------------
async function matchFaceToID() {
  if (faceMatched) return;

  try {
    setStatus("🔍 Look at the camera — comparing face to ID...", "processing");
    await new Promise(resolve => setTimeout(resolve, 2000));

    const blob     = await captureFrame();
    const formData = new FormData();
    formData.append("frame",      blob, "selfie.jpg");
    formData.append("session_id", sessionId);

    const response = await fetch(`${SERVER_URL}/match-face`, {
      method: "POST", body: formData,
    });

    const data = await response.json();

    faceMatched = true;
    sessionDone = true;

    // Stop WebSocket frame stream
    clearInterval(window.wsInterval);
    if (socket) socket.close();

    // Clear canvas
    const ctx = overlay.getContext("2d");
    ctx.clearRect(0, 0, overlay.width, overlay.height);

    if (data.verdict.verdict === "PASS") {
      completeStep(4);
      setStatus("✅ Verification complete!", "ready");
      showResult(true, data.verdict.message);
    } else if (data.verdict.verdict === "REVIEW") {
      completeStep(4);
      setStatus("⚠️ Flagged for review", "processing");
      showResult(false, data.verdict.message);
    } else {
      setStatus("❌ Verification failed", "error");
      showResult(false, data.verdict.message);
    }

  } catch (error) {
    setStatus("Face match error", "error");
    console.error(error);
  }
}


// ---------------------------------------------------------------
// MAIN — start everything
// ---------------------------------------------------------------
async function main() {
  // Step 1: get session ID from server
  const sessionOk = await initSession();
  if (!sessionOk) return;

  // Step 2: start camera
  await startCamera();

  // Step 3: open WebSocket and start streaming
  openWebSocket();
}

main();