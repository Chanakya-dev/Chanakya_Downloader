# app.py
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import uuid
import os
import shutil
import glob
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event

app = Flask(__name__)
CORS(app)

# ---- Runtime state -----------------------------------------------------------
executor = ThreadPoolExecutor(max_workers=4)  # tune per server size
active_downloads = {}  # { job_id: {future, event, file_path, job_dir, progress, cookie_file} }
user_cookie_files = {}  # { user_id: cookie_file_path }

BASE_COOKIE_DIR = os.path.join(os.getcwd(), "storage", "cookies")
os.makedirs(BASE_COOKIE_DIR, exist_ok=True)
# ---- Helpers -----------------------------------------------------------------
def make_job_dir(job_id: str) -> str:
    """Create an isolated temp directory per job (prevents user conflicts)."""
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

        # Only expose MP4 video, and audio-only (m4a/webm) which we’ll convert to MP3
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
            print(f"[DOWNLOAD] Job {job_id} progress: {percent}%")
        elif d.get("status") == "finished":
            if job_id in active_downloads:
                active_downloads[job_id]["progress"] = 100
            print(f"[DOWNLOAD] Job {job_id} finished.")
    return hook


def ydl_base_opts(cookie_file=None):
    base = {
        "quiet": True,
        "noplaylist": True,
        "forceipv4": True,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 5,
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    if cookie_file and os.path.exists(cookie_file):
        base["cookiefile"] = cookie_file
    return base


# ---- Routes ------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/api/upload-cookies", methods=["POST"])
def upload_cookies():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id") or "default_user"
    cookies = data.get("cookies")

    if not cookies:
        return jsonify({"error": "No cookies received"}), 400

    # ✅ Save in persistent storage instead of /Temp
    cookie_file = os.path.join(BASE_COOKIE_DIR, f"cookies_{user_id}.txt")
    with open(cookie_file, "w", encoding="utf-8") as f:
        f.write(cookies)

    user_cookie_files[user_id] = cookie_file
    print(f"[COOKIES] Persisted cookies for user {user_id} -> {cookie_file}")

    return jsonify({"message": "Cookies saved", "cookie_file": cookie_file})




@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    user_id = data.get("user_id")
    print(f"[INFO] /api/info called with URL: {url} by user: {user_id}")

    if not url:
        return jsonify({"error": "Missing URL"}), 400

    try:
        cookie_file = user_cookie_files.get(user_id)
        ydl_opts = ydl_base_opts(cookie_file)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = get_clean_formats(info.get("formats", []))
            print(f"[INFO] Extracted info for: {info.get('title')}")
            return jsonify({
                "title": info.get("title"),
                "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration"),
                "formats": formats
            })
    except Exception as e:
        print(f"[ERROR] Failed to extract info: {e}")
        return jsonify({"error": str(e)}), 500


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
        print(f"[DOWNLOAD] Starting job {job_id} {url} -> {opts.get('format')}")
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
            print(f"[DOWNLOAD] Job {job_id} saved to {candidates[0]}")
        else:
            print(f"[ERROR] Job {job_id} produced no output or was cancelled early.")
    except Exception as e:
        print(f"[ERROR] Download job {job_id} failed: {e}")


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    selected_format = data.get("selected_format")
    title = data.get("title", "youtube_download")
    user_id = data.get("user_id")

    print(f"[START] Starting download for: {url} - Title: {title} - User: {user_id}")

    if not url or not selected_format:
        return jsonify({"error": "Missing data"}), 400

    job_id = str(uuid.uuid4())
    cancel_event = Event()
    cookie_file = user_cookie_files.get(user_id)

    active_downloads[job_id] = {
        "future": executor.submit(perform_download, job_id, url, selected_format, title, cancel_event, cookie_file),
        "event": cancel_event,
        "file_path": None,
        "job_dir": None,
        "progress": 0,
        "cookie_file": cookie_file,
    }

    return jsonify({"job_id": job_id})


@app.route("/api/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    print(f"[CANCEL] Requested cancel for job {job_id}")
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
            print(f"[CLEANUP] Removed dir for job {job_id}")
        except Exception as e:
            print(f"[WARN] Cleanup failed for job {job_id}: {e}")

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
    app.run(host="0.0.0.0", port=port)
