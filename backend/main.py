# main.py
# This is the entry point of our backend server.
# FastAPI is a Python web framework — it lets us create "routes" (URLs)
# that the browser can talk to.

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn
import shutil
import os

# Create the FastAPI "app" — think of this as the server itself
app = FastAPI(title="Real-Time KYC System")

# ---------------------------------------------------------------
# CORS = Cross-Origin Resource Sharing
# When your browser (running on port 5500) talks to your server
# (running on port 8000), the browser blocks it by default for
# security. This tells the server to allow that connection.
# ---------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Allow all origins (fine for development)
    allow_methods=["*"],   # Allow GET, POST, etc.
    allow_headers=["*"],
)

# ---------------------------------------------------------------
# This serves our frontend files (HTML, JS, CSS) directly from
# the server, so we don't need a separate frontend server.
# ---------------------------------------------------------------
app.mount("/static", StaticFiles(directory="../frontend"), name="static")

# Make sure the uploads folder exists when the server starts
os.makedirs("../uploads", exist_ok=True)


# ---------------------------------------------------------------
# ROUTE 1: GET /
# When someone visits http://localhost:8000 in their browser,
# they get redirected to our frontend HTML page.
# ---------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root():
    with open("../frontend/index.html", "r") as f:
        return f.read()


# ---------------------------------------------------------------
# ROUTE 2: GET /health
# A simple "ping" endpoint. Useful to check the server is alive.
# Visit http://localhost:8000/health — you'll see {"status": "ok"}
# ---------------------------------------------------------------
@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "KYC server is running!"}


# ---------------------------------------------------------------
# ROUTE 3: POST /process-frame
# This is the main endpoint. The browser sends a frame (image)
# here every second. For now, we just save it and say "received".
# In future steps, this is where face detection will happen.
#
# "UploadFile" means we're receiving a file (an image) in the request.
# "async" means the server can handle multiple requests at the same
# time without waiting — important for real-time systems.
# ---------------------------------------------------------------
@app.post("/process-frame")
async def process_frame(frame: UploadFile = File(...)):
    # Save the received frame to the uploads folder
    # We always overwrite the same file (latest_frame.jpg)
    # to avoid filling up disk space
    save_path = "../uploads/latest_frame.jpg"

    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(frame.file, buffer)

    # For now, just send back a success message
    # In Step 3, this will return face landmark coordinates
    return {
        "status": "received",
        "message": "Frame saved successfully",
        "filename": frame.filename,
    }


# ---------------------------------------------------------------
# This block runs the server when you do: python main.py
# host="0.0.0.0" means "accept connections from anywhere"
# port=8000 is the port number (like a door number on the server)
# reload=True means the server auto-restarts when you save changes
# ---------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)