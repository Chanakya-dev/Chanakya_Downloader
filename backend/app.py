from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import uuid
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from threading import Event

app = Flask(__name__)
CORS(app)

# Directory setup
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Clean old files on startup
for f in os.listdir(DOWNLOAD_DIR):
    try:
        os.remove(os.path.join(DOWNLOAD_DIR, f))
    except Exception:
        pass

# Threading setup
executor = ThreadPoolExecutor(max_workers=4)
active_downloads = {}

# Get cookie path (either env or default)
COOKIE_FILE = os.getenv("YTDL_COOKIE_FILE", os.path.join(os.getcwd(), "cookies.txt"))


def sanitize_filename(title):
    return "".join(c for c in title if c.isalnum() or c in " _-.").rstrip()


def get_clean_formats(formats):
    cleaned = []
    seen_keys = {}

    for f in formats:
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
            "filesize": round(filesize / 1048576, 2),
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
        if d["status"] == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 1)
            percent = int(downloaded * 100 / total) if total > 0 else 0
            active_downloads[job_id]["progress"] = percent
        elif d["status"] == "finished":
            active_downloads[job_id]["progress"] = 100
    return hook


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing URL"}), 400

    try:
        ydl_opts = {
            'quiet': True,
            'noplaylist': True,
            'forceipv4': True,
            'cookiefile': COOKIE_FILE  # 👈 Cookie support here
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = get_clean_formats(info.get("formats", []))
            return jsonify({
                "title": info.get("title"),
                "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration"),
                "formats": formats
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def perform_download(job_id, url, selected_format, title, event):
    clean_title = sanitize_filename(title)
    file_id = f"{clean_title}_{uuid.uuid4().hex[:8]}"
    output_template = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")
    ffmpeg_path = shutil.which("ffmpeg")

    is_audio = selected_format.get("audio_only", False)
    requires_merge = selected_format.get("requires_merge", False)
    ydl_format = selected_format.get("format_id")

    ydl_opts = {
        'format': ydl_format,
        'outtmpl': output_template,
        'ffmpeg_location': ffmpeg_path,
        'noplaylist': True,
        'quiet': True,
        'cookiefile': COOKIE_FILE,  # 👈 Cookie support here
        'progress_hooks': [make_progress_hook(job_id)],
    }

    if is_audio:
        ydl_opts["postprocessors"] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    elif requires_merge:
        ydl_opts["format"] = f"{ydl_format}+bestaudio[ext=m4a]"
        ydl_opts.update({'merge_output_format': 'mp4', 'remux_video': 'mp4'})

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        for file in os.listdir(DOWNLOAD_DIR):
            if file.startswith(file_id):
                file_path = os.path.join(DOWNLOAD_DIR, file)
                if not event.is_set():
                    active_downloads[job_id]["file_path"] = file_path
                return
    except Exception:
        pass


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json()
    url = data.get("url")
    selected_format = data.get("selected_format")
    title = data.get("title", "youtube_download")

    if not url or not selected_format:
        return jsonify({"error": "Missing data"}), 400

    job_id = str(uuid.uuid4())
    cancel_event = Event()

    active_downloads[job_id] = {
        "future": executor.submit(perform_download, job_id, url, selected_format, title, cancel_event),
        "event": cancel_event,
        "file_path": None,
        "progress": 0,
    }

    return jsonify({"job_id": job_id})


@app.route("/api/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    job = active_downloads.get(job_id)
    if job:
        job["event"].set()
        return jsonify({"status": "Cancelled"})
    return jsonify({"error": "Job not found"}), 404


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
    file_path = job["file_path"]
    event = job["event"]

    if event.is_set():
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        active_downloads.pop(job_id, None)
        return jsonify({"error": "Download cancelled"}), 400

    if not file_path or not os.path.exists(file_path) or os.path.getsize(file_path) < 1024:
        active_downloads.pop(job_id, None)
        return jsonify({"error": "File not found or empty"}), 500

    filename = os.path.basename(file_path)

    def generate():
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                yield chunk
        try:
            os.remove(file_path)
        except Exception:
            pass

    active_downloads.pop(job_id, None)
    return Response(
        generate(),
        mimetype='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
