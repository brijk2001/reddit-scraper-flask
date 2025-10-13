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
from datetime import timezone


load_dotenv()
app = Flask(__name__)

# Background job storage (in-memory)
JOBS = {}
JOBS_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=2)


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


def run_scrape_job(job_id, subreddit, days):
    """Runs the scraping task in a background thread."""
    safe_set(job_id, state="running", progress=0, message="Starting scrape...")

    try:
        reddit = make_reddit()
        sub = reddit.subreddit(subreddit)
        min_ts = int((datetime.now(timezone.utc) - timedelta(days=int(days))).timestamp())

        # out_path = f"/tmp/{subreddit}_{days}d_{int(time.time())}_{job_id}.csv"
        import tempfile
        tmp_dir = tempfile.gettempdir()
        out_path = os.path.join(tmp_dir, f"{subreddit}_{days}d_{int(time.time())}_{job_id}.csv")

        f = open(out_path, "w", newline="", encoding="utf-8")
        writer = csv.writer(f)
        writer.writerow([
            "post_id", "post_title", "post_selftext", "post_author", "post_score", "post_created_utc",
            "comment_id", "comment_parent_id", "comment_body", "comment_author", "comment_score", "comment_created_utc"
        ])

        count = 0
        for submission in sub.new(limit=None):
            if int(submission.created_utc) < min_ts:
                break  # stop once we hit older posts

            submission.comment_sort = "confidence"
            submission.comments.replace_more(limit=0)
            top_comments = submission.comments

            if len(top_comments) == 0:
                writer.writerow([
                    submission.id,
                    csv_escape(submission.title),
                    csv_escape(submission.selftext),
                    getattr(getattr(submission, "author", None), "name", ""),
                    submission.score,
                    datetime.utcfromtimestamp(submission.created_utc).isoformat(),
                    "", "", "", "", "", ""
                ])
            else:
                for c in top_comments:
                    if not hasattr(c, "id"):
                        continue
                    writer.writerow([
                        submission.id,
                        csv_escape(submission.title),
                        csv_escape(submission.selftext),
                        getattr(getattr(submission, "author", None), "name", ""),
                        submission.score,
                        datetime.utcfromtimestamp(submission.created_utc).isoformat(),
                        c.id,
                        getattr(c, "parent_id", ""),
                        csv_escape(getattr(c, "body", "")),
                        getattr(getattr(c, "author", None), "name", ""),
                        getattr(c, "score", ""),
                        datetime.utcfromtimestamp(getattr(c, "created_utc", submission.created_utc)).isoformat()
                    ])

            count += 1
            if count % 10 == 0:
                safe_set(job_id, progress=min(100, count % 100), message=f"Scraped {count} posts...")
                time.sleep(0.3)
            else:
                time.sleep(0.1)

        f.close()
        safe_set(job_id, state="done", progress=100, message=f"Completed {count} posts", filename=out_path)

    except Exception as e:
        safe_set(job_id, state="error", message=f"Error: {e}")


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/start-job")
def start_job():
    """Start background scraping job"""
    try:
        subreddit = (request.form.get("subreddit") or "").strip()
        days = int(request.form.get("days") or 7)
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

    EXECUTOR.submit(run_scrape_job, job_id, subreddit, days)
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
        return abort(404, "File missing (expired)")

    return send_file(
        path,
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name=os.path.basename(path)
    )


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
    try:
        cleanup_old_jobs(3600)
    except Exception:
        pass
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
