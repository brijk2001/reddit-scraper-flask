import csv
import io
import os
import time
import uuid
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, render_template, request, jsonify, send_file, abort, url_for
from dotenv import load_dotenv
import praw

load_dotenv()

app = Flask(__name__)

# ---------------------------
# Job registry (in-memory)
# ---------------------------
# JOBS[job_id] = {
#   "state": "queued|running|done|error|cancelled",
#   "progress": 0..100,
#   "message": str,
#   "filename": "/tmp/....csv" or None,
#   "created_at": timestamp
# }
JOBS = {}
JOBS_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=2)  # tweak if needed


def make_reddit():
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    username = os.getenv("REDDIT_USERNAME")
    password = os.getenv("REDDIT_PASSWORD")
    user_agent = os.getenv("REDDIT_USER_AGENT", "reddit-scraper/0.1 by u/yourusername")

    if not client_id or not client_secret:
        raise RuntimeError("Missing REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET")

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
        user_agent=user_agent,
    )


def safe_set(job_id, **updates):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)


def csv_escape(text):
    if text is None:
        return ""
    return str(text).replace("\r", " ").replace("\n", " ")


def run_scrape_job(job_id, subreddit, days, limit):
    """Background thread target that does the scraping and writes CSV to /tmp."""
    safe_set(job_id, state="running", progress=0, message="Starting…")

    try:
        reddit = make_reddit()
        sub = reddit.subreddit(subreddit)

        # sanitize + timeframe
        limit = max(1, min(int(limit), 500))
        min_ts = int((datetime.utcnow() - timedelta(days=int(days))).timestamp())

        # Pre-scan to know total (for nicer progress)
        submissions = list(sub.new(limit=limit))
        # Filter by timeframe
        submissions = [s for s in submissions if int(s.created_utc) >= min_ts]
        total = max(len(submissions), 1)

        # prepare CSV file path
        out_path = f"/tmp/{subreddit}_{days}d_{int(time.time())}_{job_id}.csv"
        f = open(out_path, "w", newline="", encoding="utf-8")
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)

        header = [
            "post_id","post_title","post_selftext","post_author","post_score","post_created_utc",
            "comment_id","comment_parent_id","comment_body","comment_author","comment_score","comment_created_utc"
        ]
        writer.writerow(header)

        for idx, submission in enumerate(submissions, start=1):
            # top-level comments only
            submission.comment_sort = "confidence"
            submission.comments.replace_more(limit=0)
            top_level = submission.comments  # Listing of top-level Comment objects

            if len(top_level) == 0:
                writer.writerow([
                    submission.id,
                    csv_escape(getattr(submission, "title", "")),
                    csv_escape(getattr(submission, "selftext", "")),
                    getattr(getattr(submission, "author", None), "name", ""),
                    getattr(submission, "score", ""),
                    datetime.utcfromtimestamp(getattr(submission, "created_utc", int(time.time()))).isoformat(),
                    "", "", "", "", "", ""
                ])
            else:
                for c in top_level:
                    if not hasattr(c, "id"):
                        continue
                    writer.writerow([
                        submission.id,
                        csv_escape(getattr(submission, "title", "")),
                        csv_escape(getattr(submission, "selftext", "")),
                        getattr(getattr(submission, "author", None), "name", ""),
                        getattr(submission, "score", ""),
                        datetime.utcfromtimestamp(getattr(submission, "created_utc", int(time.time()))).isoformat(),
                        c.id,
                        getattr(c, "parent_id", ""),
                        csv_escape(getattr(c, "body", "")),
                        getattr(getattr(c, "author", None), "name", ""),
                        getattr(c, "score", ""),
                        datetime.utcfromtimestamp(getattr(c, "created_utc", int(time.time()))).isoformat()
                    ])

            # progress + polite delay
            prog = int((idx / total) * 100)
            safe_set(job_id, progress=prog, message=f"Processed {idx}/{total} posts…")
            if idx % 10 == 0:
                time.sleep(0.5)
            else:
                time.sleep(0.1)

        f.flush()
        f.close()
        safe_set(job_id, state="done", progress=100, message="Finished", filename=out_path)

    except Exception as e:
        safe_set(job_id, state="error", message=f"Failed: {e}")


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/start-job")
def start_job():
    """Start a background scrape job and return job_id immediately."""
    try:
        subreddit = (request.form.get("subreddit") or "").strip()
        days = int(request.form.get("days") or 7)
        limit = int(request.form.get("limit") or 100)
        if not subreddit:
            return abort(400, "Subreddit is required.")
    except Exception:
        return abort(400, "Invalid input.")

    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "state": "queued",
            "progress": 0,
            "message": "Queued",
            "filename": None,
            "created_at": time.time(),
        }

    # submit to executor
    EXECUTOR.submit(run_scrape_job, job_id, subreddit, days, limit)
    return jsonify({"job_id": job_id})


@app.get("/job-status/<job_id>")
def job_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "not_found"}), 404

    resp = {
        "state": job["state"],
        "progress": job["progress"],
        "message": job.get("message", ""),
    }
    if job["state"] == "done" and job.get("filename"):
        resp["download_url"] = url_for("download_job", job_id=job_id, _external=False)
    return jsonify(resp)


@app.get("/download/<job_id>")
def download_job(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job["state"] != "done" or not job.get("filename"):
        return abort(404, "File not ready")

    path = job["filename"]
    if not os.path.exists(path):
        return abort(404, "File missing (expired?)")

    # Use original filename
    download_name = os.path.basename(path)
    return send_file(
        path,
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name=download_name
    )


# Optional: simple cleanup of old jobs in memory (/tmp files)
def cleanup_old_jobs(max_age_seconds=3600):
    now = time.time()
    with JOBS_LOCK:
        for jid, job in list(JOBS.items()):
            if now - job.get("created_at", now) > max_age_seconds:
                fn = job.get("filename")
                if fn and os.path.exists(fn):
                    try:
                        os.remove(fn)
                    except Exception:
                        pass
                JOBS.pop(jid, None)


@app.after_request
def after_request(resp):
    # opportunistic cleanup every response
    try:
        cleanup_old_jobs(3600)  # 1 hour retention
    except Exception:
        pass
    return resp


if __name__ == "__main__":
    # Local dev
    app.run(host="0.0.0.0", port=5000, debug=True)
