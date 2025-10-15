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
LISTING_CAP = 1000            # practical Reddit listing cap (~1000)
PROGRESS_POLL_DELAY_FAST = 0.1
PROGRESS_POLL_DELAY_SLOW = 0.3
JOB_RETENTION_SECONDS = 3600  # keep job metadata & CSVs ~1h

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
#   "from_date": "YYYY-MM-DD",   # newest included
#   "to_date": "YYYY-MM-DD",     # oldest included
#   "cap_hit": bool,
#   "requested_from": "YYYY-MM-DD",
#   "requested_to": "YYYY-MM-DD"
# }
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


def parse_date_yyyy_mm_dd(s: str) -> datetime:
    """Parse 'YYYY-MM-DD' into a timezone-aware UTC midnight datetime."""
    dt = datetime.strptime(s, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def run_scrape_job(job_id, subreddit, start_date_str, end_date_str):
    """
    Background task:
      - Iterates subreddit.new(limit=None) (newest → older)
      - Skips posts newer than end_date (created_utc > max_ts)
      - Stops when older than start_date (created_utc < min_ts)
      - Stops if LISTING_CAP reached
    """
    safe_set(job_id, state="running", progress=0, message="Starting…")

    try:
        # --- Validate & compute date window (inclusive) ---
        start_dt = parse_date_yyyy_mm_dd(start_date_str)  # YYYY-MM-DDT00:00:00Z
        # end of day inclusive: 23:59:59.999...
        end_dt = parse_date_yyyy_mm_dd(end_date_str) + timedelta(days=1) - timedelta(microseconds=1)

        if end_dt < start_dt:
            raise ValueError("End date must be on or after start date.")

        min_ts = int(start_dt.timestamp())
        max_ts = int(end_dt.timestamp())

        # --- Reddit client ---
        reddit = make_reddit()
        sub = reddit.subreddit(subreddit)

        # --- CSV output (cross-platform tempdir) ---
        tmp_dir = tempfile.gettempdir()
        out_path = os.path.join(
            tmp_dir,
            f"{subreddit}_{start_date_str}_to_{end_date_str}_{int(time.time())}_{job_id}.csv"
        )

        f = open(out_path, "w", newline="", encoding="utf-8")
        writer = csv.writer(f)
        writer.writerow([
            "post_id", "post_title", "post_selftext", "post_author", "post_score", "post_created_utc",
            "comment_id", "comment_parent_id", "comment_body", "comment_author", "comment_score", "comment_created_utc"
        ])

        # --- Iterate listing ---
        count = 0
        cap_hit = False
        newest_dt_included = None  # first included post (newest in range)
        oldest_dt_included = None  # last included post (oldest in range)

        for submission in sub.new(limit=None):
            created_utc = int(getattr(submission, "created_utc", 0))

            # too new for our window → skip until we get into range
            if created_utc > max_ts:
                continue

            # too old → we're past the window; stop the job
            if created_utc < min_ts:
                break

            # Now we are within [min_ts, max_ts] → include this submission
            this_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
            if newest_dt_included is None:
                newest_dt_included = this_dt  # first included is the newest in-range
            oldest_dt_included = this_dt

            # fetch top-level comments only
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
            prog = min(99, int((count / LISTING_CAP) * 100))
            if count % 10 == 0:
                safe_set(job_id, progress=prog, message=f"Scraped {count} posts…")
                time.sleep(PROGRESS_POLL_DELAY_SLOW)
            else:
                time.sleep(PROGRESS_POLL_DELAY_FAST)

            # stop at listing cap
            if count >= LISTING_CAP:
                cap_hit = True
                break

        f.flush()
        f.close()

        # Prepare final message
        from_date = newest_dt_included.date().isoformat() if newest_dt_included else "—"
        to_date = oldest_dt_included.date().isoformat() if oldest_dt_included else "—"
        req_from = start_dt.date().isoformat()
        req_to = end_dt.date().isoformat()

        cap_note = " (API listing cap ~1000 reached)" if cap_hit else ""
        final_msg = (f"Finished {count} posts. "
                     f"Requested: {req_from} → {req_to}. "
                     f"Covered: {to_date} → {from_date}{cap_note}")

        safe_set(
            job_id,
            state="done",
            progress=100,
            message=final_msg,
            filename=out_path,
            count=count,
            from_date=from_date,
            to_date=to_date,
            cap_hit=cap_hit,
            requested_from=req_from,
            requested_to=req_to
        )

    except Exception as e:
        safe_set(job_id, state="error", message=f"Failed: {e}")


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/start-job")
def start_job():
    """Start a background scrape for a date range (UTC)."""
    try:
        subreddit = (request.form.get("subreddit") or "").strip()
        start_date = (request.form.get("start_date") or "").strip()
        end_date = (request.form.get("end_date") or "").strip()
        if not subreddit:
            return abort(400, "Subreddit is required.")
        if not start_date or not end_date:
            return abort(400, "Start and end dates are required (YYYY-MM-DD).")

        # Validate parse here to fail fast
        _ = parse_date_yyyy_mm_dd(start_date)
        _ = parse_date_yyyy_mm_dd(end_date)
    except Exception:
        return abort(400, "Invalid input. Use YYYY-MM-DD for dates.")

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
            "cap_hit": False,
            "requested_from": start_date,
            "requested_to": end_date,
        }

    EXECUTOR.submit(run_scrape_job, job_id, subreddit, start_date, end_date)
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
        "count": job.get("count"),
        "from_date": job.get("from_date"),
        "to_date": job.get("to_date"),
        "requested_from": job.get("requested_from"),
        "requested_to": job.get("requested_to"),
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
    app.run(host="0.0.0.0", port=5000, debug=True)
