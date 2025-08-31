import logging
import os
import shutil
import glob
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ["http://localhost:3000", "https://your-frontend-domain.com"]}})  # Update with your frontend URL

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Runtime state
executor = ThreadPoolExecutor(max_workers=2)  # Reduced for Render free tier
active_downloads = {}  # { job_id: {future, event, file_path, job_dir, progress, cookie_file} }
user_cookie_files = {}  # { user_id: cookie_file_path }
BASE_COOKIE_DIR = os.path.join("/opt/render/project", "storage", "cookies")  # Persistent storage for Render
os.makedirs(BASE_COOKIE_DIR, exist_ok=True)

# Helpers
def make_job_dir(job_id: str) -> str:
    """Create an isolated temp directory per job."""
    d = os.path.join(tempfile.gettempdir(), "ytjobs", job_id)
    os.makedirs(d, exist_ok=True)
    return d

def sanitize_filename(title: str) -> str:
    return "".join(c for c in (title or "") if c.isalnum() or c in " _-.").rstrip() or "youtube_download"

def get_clean_formats(formats):
    cleaned = []
    seen_keys = {}
    for f in formats or []:
        format_id = f.get("format_id")
        ext = f.get("ext")
        height = f.get("height")
        filesize = f.get("filesize") or 0
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        abr = f.get("abr")
        if not format_id or not ext or not filesize:
            continue
        is_audio_only = vcodec == "none" and acodec != "none"
        is_video_only = vcodec != "none" and acodec == "none"
        if not (ext == "mp4" or (is_audio_only and ext in ["m4a", "webm"])):
            continue
        cleaned_format = {
            "format_id": format_id,
            "ext": "mp3" if is_audio_only else ext,
            "filesize": round(filesize / 1048576, 2),  # bytes -> MB
            "vcodec": vcodec,
            "acodec": acodec,
            "audio_only": is_audio_only,
            "requires_merge": is_video_only,
            "abr": abr if is_audio_only else None,
            "resolution": int(height) if height else None,
        }
        key = f"audio_{abr}" if is_audio_only else f"video_{height}"
        if key not in seen_keys or seen_keys[key]["filesize"] > cleaned_format["filesize"]:
            seen_keys[key] = cleaned_format
    return list(seen_keys.values())

def make_progress_hook(job_id):
    def hook(d):
        if d.get("status") == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            percent = int(downloaded * 100 / total) if total > 0 else 0
            if job_id in active_downloads:
                active_downloads[job_id]["progress"] = max(0, min(100, percent))
            logger.info(f"[DOWNLOAD] Job {job_id} progress: {percent}%")
        elif d.get("status") == "finished":
            if job_id in active_downloads:
                active_downloads[job_id]["progress"] = 100
            logger.info(f"[DOWNLOAD] Job {job_id} finished.")
    return hook

def ydl_base_opts(cookie_file=None):
    base = {
        "quiet": True,
        "noplaylist": True,
        "forceipv4": True,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 2,
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    if cookie_file and os.path.exists(cookie_file):
        base["cookiefile"] = cookie_file
    return base

# Routes
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/api/upload-cookies", methods=["POST"])
def upload_cookies():
    user_id = request.form.get("user_id") or "default_user"
    if "cookies_file" not in request.files:
        logger.error(f"[COOKIES] No file part in request for user {user_id}")
        return jsonify({"error": "No cookies file uploaded. Please upload a cookies.txt file."}), 400

    file = request.files["cookies_file"]
    if file.filename == "":
        logger.error(f"[COOKIES] No selected file for user {user_id}")
        return jsonify({"error": "No file selected. Please upload a cookies.txt file."}), 400

    if not file.filename.endswith(".txt"):
        logger.error(f"[COOKIES] Invalid file type for user {user_id}: {file.filename}")
        return jsonify({"error": "Invalid file type. Please upload a cookies.txt file."}), 400

    try:
        cookies_txt = file.read().decode("utf-8")
        required_cookies = ["SID", "__Secure-3PSID"]
        cookies_lines = cookies_txt.splitlines()
        has_required_cookies = any(any(cookie in line for cookie in required_cookies) for line in cookies_lines)
        if not has_required_cookies:
            logger.error(f"[COOKIES] Invalid cookies for user {user_id}: Missing required cookies")
            return jsonify({"error": "Invalid cookies: Missing required YouTube authentication cookies (e.g., SID, __Secure-3PSID). Please export cookies using 'Get cookies.txt LOCALLY'."}), 400

        cookie_file = os.path.join(BASE_COOKIE_DIR, f"cookies_{user_id}.txt")
        with open(cookie_file, "w", encoding="utf-8") as f:
            f.write(cookies_txt)
        os.chmod(cookie_file, 0o600)
        user_cookie_files[user_id] = cookie_file
        logger.info(f"[COOKIES] Persisted cookies for user {user_id} -> {cookie_file}")
        return jsonify({"message": "Cookies saved", "cookie_file": cookie_file})
    except Exception as e:
        logger.error(f"[COOKIES] Failed to save cookies for user {user_id}: {e}")
        return jsonify({"error": f"Failed to save cookies: {str(e)}"}), 500

@app.route("/api/test-cookies", methods=["POST"])
def test_cookies():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id") or "default_user"
    test_url = data.get("test_url") or "https://www.youtube.com/watch?v=restricted_video_id"  # Replace with a known restricted video ID

    cookie_file = user_cookie_files.get(user_id)
    if not cookie_file or not os.path.exists(cookie_file):
        logger.error(f"[COOKIES] No cookies found for user {user_id}")
        return jsonify({"error": "No cookies found. Please upload a cookies.txt file."}), 400

    try:
        ydl_opts = ydl_base_opts(cookie_file)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(test_url, download=False)
            logger.info(f"[COOKIES] Cookie test successful for user {user_id}: {info.get('title')}")
            return jsonify({
                "status": "success",
                "title": info.get("title"),
                "is_restricted": bool(info.get("age_limit") or info.get("is_private")),
            })
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"[COOKIES] Cookie test failed for user {user_id}: {e}")
        if "sign in" in str(e).lower() or "login required" in str(e).lower():
            if os.path.exists(cookie_file):
                os.remove(cookie_file)
            user_cookie_files.pop(user_id, None)
            return jsonify({"error": "Cookies invalid or expired. Please re-upload a valid cookies.txt file."}), 401
        return jsonify({"error": "Failed to access video. Invalid or restricted URL."}), 400
    except Exception as e:
        logger.error(f"[COOKIES] Cookie test failed for user {user_id}: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route("/api/has-cookies", methods=["POST"])
def has_cookies():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id") or "default_user"
    cookie_file = user_cookie_files.get(user_id)
    if cookie_file and os.path.exists(cookie_file):
        return jsonify({"has_cookies": True})
    return jsonify({"has_cookies": False})

@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    user_id = data.get("user_id")
    logger.info(f"[INFO] /api/info called with URL: {url} by user: {user_id}")

    if not url:
        return jsonify({"error": "Missing URL"}), 400

    try:
        cookie_file = user_cookie_files.get(user_id)
        ydl_opts = ydl_base_opts(cookie_file)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = get_clean_formats(info.get("formats", []))
            logger.info(f"[INFO] Extracted info for: {info.get('title')}")
            return jsonify({
                "title": info.get("title"),
                "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration"),
                "formats": formats
            })
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"[ERROR] yt-dlp failed: {e}")
        if "sign in" in str(e).lower() or "login required" in str(e).lower():
            cookie_file = user_cookie_files.get(user_id)
            if cookie_file and os.path.exists(cookie_file):
                os.remove(cookie_file)
            user_cookie_files.pop(user_id, None)
            return jsonify({"error": "Cookies invalid or expired. Please re-upload a valid cookies.txt file."}), 401
        return jsonify({"error": "Failed to fetch video info. Invalid or restricted URL."}), 400
    except Exception as e:
        logger.error(f"[ERROR] Failed to extract info: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

def perform_download(job_id, url, selected_format, title, event, cookie_file=None):
    clean_title = sanitize_filename(title)
    job_dir = make_job_dir(job_id)
    file_id = f"{clean_title}_{uuid.uuid4().hex[:8]}"
    output_template = os.path.join(job_dir, f"{file_id}.%(ext)s")
    ffmpeg_path = shutil.which("ffmpeg")

    is_audio = bool(selected_format.get("audio_only"))
    requires_merge = bool(selected_format.get("requires_merge"))
    ydl_format = selected_format.get("format_id")

    opts = ydl_base_opts(cookie_file)
    opts.update({
        "format": ydl_format,
        "outtmpl": output_template,
        "ffmpeg_location": ffmpeg_path,
        "progress_hooks": [make_progress_hook(job_id)],
    })

    if is_audio:
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    elif requires_merge:
        opts["format"] = f"{ydl_format}+bestaudio[ext=m4a]"
        opts.update({"merge_output_format": "mp4", "remux_video": "mp4"})

    try:
        logger.info(f"[DOWNLOAD] Starting job {job_id} {url} -> {opts.get('format')}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        candidates = sorted(
            glob.glob(os.path.join(job_dir, f"{file_id}.*")),
            key=lambda p: os.path.getmtime(p),
            reverse=True
        )

        if candidates and not event.is_set():
            active_downloads[job_id]["file_path"] = candidates[0]
            active_downloads[job_id]["job_dir"] = job_dir
            logger.info(f"[DOWNLOAD] Job {job_id} saved to {candidates[0]}")
        else:
            logger.error(f"[ERROR] Job {job_id} produced no output or was cancelled early.")
    except Exception as e:
        logger.error(f"[ERROR] Download job {job_id} failed: {e}")

@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    selected_format = data.get("selected_format")
    title = data.get("title", "youtube_download")
    user_id = data.get("user_id")

    logger.info(f"[START] Starting download for: {url} - Title: {title} - User: {user_id}")

    if not url or not selected_format:
        return jsonify({"error": "Missing data"}), 400

    job_id = str(uuid.uuid4())
    cancel_event = Event()
    cookie_file = user_cookie_files.get(user_id)

    active_downloads[job_id] = {
        "future": executor.submit(
            perform_download, job_id, url, selected_format, title, cancel_event, cookie_file
        ),
        "event": cancel_event,
        "file_path": None,
        "job_dir": None,
        "progress": 0,
        "cookie_file": cookie_file,
    }

    return jsonify({"job_id": job_id})

@app.route("/api/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    logger.info(f"[CANCEL] Requested cancel for job {job_id}")
    job = active_downloads.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    job["event"].set()
    return jsonify({"status": "Cancelled"})

@app.route("/api/progress/<job_id>", methods=["GET"])
def get_progress(job_id):
    job = active_downloads.get(job_id)
    if job:
        return jsonify({"progress": job.get("progress", 0)})
    return jsonify({"error": "Job not found"}), 404

@app.route("/api/download-file/<job_id>", methods=["GET"])
def get_file(job_id):
    job = active_downloads.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    job["future"].result()
    file_path = job.get("file_path")
    job_dir = job.get("job_dir")
    event = job["event"]

    def cleanup_dir():
        try:
            if job_dir and os.path.exists(job_dir):
                shutil.rmtree(job_dir, ignore_errors=True)
            logger.info(f"[CLEANUP] Removed dir for job {job_id}")
        except Exception as e:
            logger.warning(f"[WARN] Cleanup failed for job {job_id}: {e}")

    if event.is_set():
        cleanup_dir()
        active_downloads.pop(job_id, None)
        return jsonify({"error": "Download cancelled"}), 400

    if not file_path or not os.path.exists(file_path) or os.path.getsize(file_path) < 1024:
        cleanup_dir()
        active_downloads.pop(job_id, None)
        return jsonify({"error": "File not found or empty"}), 500

    filename = os.path.basename(file_path)

    def generate():
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                yield chunk
        cleanup_dir()

    active_downloads.pop(job_id, None)
    return Response(
        generate(),
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)