import csv
import os
import time
import uuid
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, render_template, request, jsonify, send_file, abort, url_for
from dotenv import load_dotenv
import praw

load_dotenv()
app = Flask(__name__)

# ---------------------------
# Config / constants
# ---------------------------
# Reddit listing endpoints effectively cap around ~1000 items.
LISTING_CAP = 1000           # stop scraping when this many posts are processed
PROGRESS_POLL_DELAY_FAST = 0.1
PROGRESS_POLL_DELAY_SLOW = 0.3
JOB_RETENTION_SECONDS = 3600  # keep CSVs & job entries for 1h

# ---------------------------
# In-memory job registry
# ---------------------------
# JOBS[job_id] = {
#   "state": "queued|running|done|error",
#   "progress": 0..100,
#   "message": str,
#   "filename": "/tmp/....csv" or None,
#   "created_at": ts,
#   "count": int,
#   "from_date": "YYYY-MM-DD",   # newest seen
#   "to_date": "YYYY-MM-DD",     # oldest seen
#   "cap_hit": bool
# }
JOBS = {}
JOBS_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=2)  # adjust as you like


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
    """
    Background task:
      - iterates subreddit.new(limit=None) from newest -> older
      - stops when posts fall below timeframe (min_ts) OR LISTING_CAP reached
      - writes CSV to system temp dir
      - records count + coverage window + whether cap was hit
    """
    safe_set(job_id, state="running", progress=0, message="Starting…")

    try:
        reddit = make_reddit()
        sub = reddit.subreddit(subreddit)

        # timeframe lower bound (UTC-aware)
        min_ts = int((datetime.now(timezone.utc) - timedelta(days=int(days))).timestamp())

        # cross-platform temp file path
        tmp_dir = tempfile.gettempdir()
        out_path = os.path.join(tmp_dir, f"{subreddit}_{days}d_{int(time.time())}_{job_id}.csv")

        # open CSV
        f = open(out_path, "w", newline="", encoding="utf-8")
        writer = csv.writer(f)
        writer.writerow([
            "post_id", "post_title", "post_selftext", "post_author", "post_score", "post_created_utc",
            "comment_id", "comment_parent_id", "comment_body", "comment_author", "comment_score", "comment_created_utc"
        ])

        count = 0
        cap_hit = False
        newest_dt = None  # first (newest) post datetime encountered
        oldest_dt = None  # oldest post datetime encountered (within timeframe)

        for submission in sub.new(limit=None):
            created_utc = int(getattr(submission, "created_utc", 0))
            # We have reached older than timeframe -> stop
            if created_utc < min_ts:
                break

            # set coverage window
            this_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
            if newest_dt is None:
                newest_dt = this_dt  # first item is the newest (listing order)
            oldest_dt = this_dt     # will keep updating as we go older

            # fetch only top-level comments
            submission.comment_sort = "confidence"
            submission.comments.replace_more(limit=0)
            top_comments = submission.comments

            if len(top_comments) == 0:
                writer.writerow([
                    submission.id,
                    csv_escape(submission.title),
                    csv_escape(getattr(submission, "selftext", "")),
                    getattr(getattr(submission, "author", None), "name", ""),
                    getattr(submission, "score", ""),
                    this_dt.isoformat(),
                    "", "", "", "", "", ""
                ])
            else:
                for c in top_comments:
                    if not hasattr(c, "id"):
                        continue
                    writer.writerow([
                        submission.id,
                        csv_escape(submission.title),
                        csv_escape(getattr(submission, "selftext", "")),
                        getattr(getattr(submission, "author", None), "name", ""),
                        getattr(submission, "score", ""),
                        this_dt.isoformat(),
                        getattr(c, "id", ""),
                        getattr(c, "parent_id", ""),
                        csv_escape(getattr(c, "body", "")),
                        getattr(getattr(c, "author", None), "name", ""),
                        getattr(c, "score", ""),
                        datetime.fromtimestamp(
                            int(getattr(c, "created_utc", created_utc)), tz=timezone.utc
                        ).isoformat()
                    ])

            # progress + pacing
            count += 1
            # progress is relative to the cap, to avoid jumping from 99→100 too early
            prog = min(99, int((count / LISTING_CAP) * 100))
            if count % 10 == 0:
                safe_set(job_id, progress=prog, message=f"Scraped {count} posts…")
                time.sleep(PROGRESS_POLL_DELAY_SLOW)
            else:
                time.sleep(PROGRESS_POLL_DELAY_FAST)

            # STOP once we hit the listing cap
            if count >= LISTING_CAP:
                cap_hit = True
                break

        f.flush()
        f.close()

        from_date = newest_dt.date().isoformat() if newest_dt else "?"
        to_date = oldest_dt.date().isoformat() if oldest_dt else "?"
        cap_note = " (API listing cap ~1000 reached)" if cap_hit else ""
        final_msg = f"Finished {count} posts. Coverage: {to_date} → {from_date}{cap_note}"

        safe_set(
            job_id,
            state="done",
            progress=100,
            message=final_msg,
            filename=out_path,
            count=count,
            from_date=from_date,
            to_date=to_date,
            cap_hit=cap_hit
        )

    except Exception as e:
        safe_set(job_id, state="error", message=f"Failed: {e}")


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/start-job")
def start_job():
    try:
        subreddit = (request.form.get("subreddit") or "").strip()
        days = int(request.form.get("days") or 7)
        if not subreddit:
            return abort(400, "Subreddit is required.")
        if days < 1 or days > 365:
            return abort(400, "Days must be between 1 and 365.")
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
            "count": 0,
            "from_date": None,
            "to_date": None,
            "cap_hit": False
        }

    EXECUTOR.submit(run_scrape_job, job_id, subreddit, days)
    return jsonify({"job_id": job_id})


@app.get("/job-status/<job_id>")
def job_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "not_found"}), 404

    # Include the extra fields in the status JSON so the UI (or you) can show them
    resp = {
        "state": job["state"],
        "progress": job["progress"],
        "message": job.get("message", ""),
        "count": job.get("count"),
        "from_date": job.get("from_date"),
        "to_date": job.get("to_date"),
        "cap_hit": job.get("cap_hit"),
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

    return send_file(
        path,
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name=os.path.basename(path)
    )


def cleanup_old_jobs(max_age_seconds=JOB_RETENTION_SECONDS):
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
        cleanup_old_jobs(JOB_RETENTION_SECONDS)
    except Exception:
        pass
    return resp


if __name__ == "__main__":
    # Local dev
    app.run(host="0.0.0.0", port=5000, debug=True)
