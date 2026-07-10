// app.js
// This file runs in the browser and does three things:
//   1. Asks the user for camera permission and shows the live feed
//   2. Captures a frame (snapshot) from the video every second
//   3. Sends that frame to our Python server and shows the response

// ---------------------------------------------------------------
// Grab references to the HTML elements we'll work with
// document.getElementById("...") finds an element by its id=""
// ---------------------------------------------------------------
const video        = document.getElementById("video");
const overlay      = document.getElementById("overlay");
const statusDot    = document.getElementById("statusDot");
const statusText   = document.getElementById("statusText");
const serverResp   = document.getElementById("serverResponse");

// The canvas is used to "snapshot" a frame from the video
// We never display this canvas — it's a behind-the-scenes tool
const captureCanvas = document.createElement("canvas");
const captureCtx    = captureCanvas.getContext("2d");

// How often to send a frame to the server (in milliseconds)
// 1000ms = 1 second. We'll increase this later when doing real ML.
const FRAME_INTERVAL_MS = 1000;

// The URL of our Python server
const SERVER_URL = "http://localhost:8000";


// ---------------------------------------------------------------
// FUNCTION: setStatus
// Updates the status bar at the bottom of the video
// color can be: "green", "yellow", "red"
// ---------------------------------------------------------------
function setStatus(message, color = "green") {
  statusText.textContent = message;
  statusDot.style.background = color === "green"  ? "#22c55e"
                             : color === "yellow" ? "#eab308"
                             : "#ef4444";
}


// ---------------------------------------------------------------
// FUNCTION: startCamera
// Asks the browser for camera access, then plays the feed
// in the <video> element.
//
// "async/await" means: do this, but wait for the result before
// moving on. Camera access is not instant — we have to wait.
// ---------------------------------------------------------------
async function startCamera() {
  try {
    setStatus("Requesting camera access...", "yellow");

    // getUserMedia asks the user "allow camera?"
    // If they click Allow, we get a "stream" of video data
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        width:  { ideal: 1280 },  // prefer HD
        height: { ideal: 720 },
        facingMode: "user"        // front camera (on phones)
      },
      audio: false  // we don't need audio for KYC
    });

    // Attach the camera stream to the <video> element
    video.srcObject = stream;

    // Wait until the video is actually playing before we continue
    await new Promise((resolve) => {
      video.onloadedmetadata = () => {
        video.play();
        resolve();
      };
    });

    // Size the overlay canvas to match the video exactly
    overlay.width  = video.videoWidth;
    overlay.height = video.videoHeight;
    captureCanvas.width  = video.videoWidth;
    captureCanvas.height = video.videoHeight;

    setStatus("Camera active — sending frames to server", "green");

    // Start sending frames to the server
    startSendingFrames();

  } catch (error) {
    // This happens if the user clicks "Block" on camera permission
    setStatus("Camera access denied: " + error.message, "red");
    console.error("Camera error:", error);
  }
}


// ---------------------------------------------------------------
// FUNCTION: captureFrame
// Takes a single snapshot from the live video and returns it
// as a "Blob" (a binary file, like a .jpg image in memory).
// ---------------------------------------------------------------
function captureFrame() {
  // Draw the current video frame onto our hidden canvas
  captureCtx.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);

  // Return a Promise that resolves with a JPEG blob
  // quality 0.85 = 85% JPEG quality (good balance of size vs clarity)
  return new Promise((resolve) => {
    captureCanvas.toBlob(resolve, "image/jpeg", 0.85);
  });
}


// ---------------------------------------------------------------
// FUNCTION: sendFrameToServer
// Takes one snapshot and POSTs it to our Python server.
// The server saves it and sends back a JSON response.
// ---------------------------------------------------------------
async function sendFrameToServer() {
  try {
    // Step 1: capture a frame from the video
    const blob = await captureFrame();

    // Step 2: wrap it in a FormData object
    // FormData is how browsers send files to servers (like a form upload)
    const formData = new FormData();
    formData.append("frame", blob, "frame.jpg");  // "frame" must match
                                                   // the parameter name
                                                   // in main.py

    // Step 3: POST the frame to the server
    const response = await fetch(`${SERVER_URL}/process-frame`, {
      method: "POST",
      body: formData,
    });

    // Step 4: parse the JSON response from the server
    const data = await response.json();

    // Step 5: show the response in the UI
    serverResp.textContent = JSON.stringify(data, null, 2);
    serverResp.style.color = "var(--green)";

  } catch (error) {
    // This usually means the server is not running
    serverResp.textContent = "Server not reachable: " + error.message;
    serverResp.style.color = "var(--red)";
    setStatus("Cannot reach server — is it running?", "red");
  }
}


// ---------------------------------------------------------------
// FUNCTION: startSendingFrames
// Calls sendFrameToServer every FRAME_INTERVAL_MS milliseconds.
// setInterval is like a repeating timer.
// ---------------------------------------------------------------
function startSendingFrames() {
  setInterval(sendFrameToServer, FRAME_INTERVAL_MS);
}


// ---------------------------------------------------------------
// MAIN: Run everything
// This is the entry point — called as soon as the page loads.
// ---------------------------------------------------------------
startCamera();