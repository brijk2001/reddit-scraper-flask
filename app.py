import os, csv, time, uuid, tempfile, threading, random, requests
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template, request, jsonify, send_file, abort, url_for
from dotenv import load_dotenv
import praw
import logging # Added for better error logging

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()
app = Flask(__name__)

# ---------- CONFIG ----------
# Max posts to pull per job (can be increased, but 2500 is a good starting point for stability)
LISTING_CAP_WITH_COMMENTS = 1000
LISTING_CAP_POSTS_ONLY = 2500 
PROGRESS_POLL_DELAY_FAST = 0.08
PROGRESS_POLL_DELAY_SLOW = 0.25
JOB_RETENTION_SECONDS = 3600

# Recommended Pushshift mirror
PUSHSHIFT_BASE_URLS = [
    u.strip() for u in os.getenv(
        "PUSHSHIFT_BASE_URLS",
        "https://api.pullpush.io/reddit/search/submission/"
    ).split(",") if u.strip()
]
# Chunking size in seconds (24 hours) - helps find posts in specific windows
DAILY_CHUNK_SECONDS = int(os.getenv("DAILY_CHUNK_SECONDS", "86400"))
PUSHSHIFT_PAGE_SIZE = int(os.getenv("PUSHSHIFT_PAGE_SIZE", "500"))
PUSHSHIFT_MAX_RETRIES = int(os.getenv("PUSHSHIFT_MAX_RETRIES", "4"))
PUSHSHIFT_DAILY_ATTEMPTS = int(os.getenv("PUSHSHIFT_DAILY_ATTEMPTS", "2"))
PUSHSHIFT_REQUEST_TIMEOUT = int(os.getenv("PUSHSHIFT_REQUEST_TIMEOUT", "30"))

JOBS, JOBS_LOCK = {}, threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=2)

# ---------- UTILITIES ----------
def make_reddit():
    # PRAW setup: Ensure you have REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, 
    # REDDIT_USERNAME, REDDIT_PASSWORD, and REDDIT_USER_AGENT set in your .env file
    # for PRAW to function correctly.
    try:
        return praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            username=os.getenv("REDDIT_USERNAME"),
            password=os.getenv("REDDIT_PASSWORD"),
            user_agent=os.getenv("REDDIT_USER_AGENT"),
        )
    except Exception as e:
        logging.error(f"PRAW initialization failed: {e}")
        raise

def csv_escape(t): return "" if t is None else str(t).replace("\r"," ").replace("\n"," ")
def parse_date(s): return datetime.strptime(s,"%Y-%m-%d").replace(tzinfo=timezone.utc)
def safe_set(j,**u):
    with JOBS_LOCK:
        if j in JOBS: JOBS[j].update(u)

def _ps_get_json(session, base_url, params, timeout, max_retries):
    """Handles API requests with retries and exponential backoff for reliability."""
    backoff = 0.5
    for attempt in range(max_retries + 1):
        try:
            headers = {"User-Agent": os.getenv("REDDIT_USER_AGENT", "RedditScraper/1.0")}
            resp = session.get(base_url, params=params, timeout=timeout, headers=headers)
            resp.raise_for_status() # Raise for bad status codes (400, 500)
            return resp.json()
        except requests.exceptions.RequestException as e:
            logging.warning(f"Pushshift request failed (Attempt {attempt+1}/{max_retries+1}): {e}")
            if attempt >= max_retries: raise Exception(f"Failed after {max_retries+1} attempts: {e}")
            time.sleep(backoff + random.random() * 0.35)
            backoff = min(backoff * 2, 6)
        except Exception as e:
            logging.error(f"Unexpected error in Pushshift API call: {e}")
            raise

def iter_pushshift_ids_daily_anchored(sub, after_ts, before_ts, max_results):
    """
    Core scraping function. Iterates backwards, daily, with internal pagination 
    and retries to maximize historical data retrieval.
    """
    sess = requests.Session()
    emitted = 0
    # Start checking from the most recent timestamp in the range
    current_end_ts = before_ts 
    empty_days, total_days = 0, 0
    
    # Loop backwards through time, day by day (or chunk by chunk)
    while current_end_ts >= after_ts and emitted < max_results:
        # Calculate the start of the current daily chunk
        day_start_ts = max(after_ts, current_end_ts - DAILY_CHUNK_SECONDS + 1)
        total_days += 1
        
        # This cursor is the anchor for pagination *within* the current day
        cursor_before_ts = current_end_ts 
        day_successful_data_fetch = False

        # Attempt to get data for this day multiple times (to handle Pushshift unreliability)
        for attempt in range(PUSHSHIFT_DAILY_ATTEMPTS):
            min_seen_ts = None # Reset the anchor for each day attempt
            day_fetched_ids = set() # Track unique IDs across attempts for this day

            # Pagination loop: runs until the cursor goes before the start of the day
            while emitted < max_results and cursor_before_ts >= day_start_ts:
                params = {
                    "subreddit": sub,
                    "after": day_start_ts,
                    "before": cursor_before_ts,
                    "size": min(PUSHSHIFT_PAGE_SIZE, max_results - emitted),
                    "sort": "desc",
                    "sort_type": "created_utc",
                    "fields": "id,created_utc",
                }
                
                j = None
                for base in PUSHSHIFT_BASE_URLS:
                    try:
                        j = _ps_get_json(sess, base, params, PUSHSHIFT_REQUEST_TIMEOUT, PUSHSHIFT_MAX_RETRIES)
                        break
                    except Exception:
                        continue # Try the next base URL/mirror
                
                if not j or not j.get("data"):
                    # No data returned for this page/anchor, stop paginating for this attempt
                    break 

                data = j["data"]
                new_data_emitted = 0

                for d in data:
                    sid, cu = d.get("id"), d.get("created_utc")
                    if not sid or not cu: continue
                    cu = int(cu)
                    
                    if cu < day_start_ts or cu > current_end_ts: continue 
                    if sid in day_fetched_ids: continue # Skip if already yielded in a previous page/attempt

                    yield sid, cu # SUCCESS: Yield the post ID and timestamp
                    day_fetched_ids.add(sid)
                    emitted += 1
                    new_data_emitted += 1
                    day_successful_data_fetch = True
                    # Update the anchor (oldest post seen so far in this day's run)
                    if min_seen_ts is None or cu < min_seen_ts: min_seen_ts = cu
                    if emitted >= max_results: return # Hit the job cap

                
                # Crucial step: move the cursor to just before the oldest post we just saw
                if min_seen_ts is None or new_data_emitted == 0: 
                    # If we got data but couldn't find a new/valid anchor, stop paginating
                    break 
                
                cursor_before_ts = min_seen_ts - 1
                
                time.sleep(0.12) # Respect Pushshift rate limits

            # Check if this day attempt yielded any data
            if day_successful_data_fetch:
                break # Exit the PUSHSHIFT_DAILY_ATTEMPTS loop, we got data for this day
            else: 
                # If attempt failed, wait and retry the *entire day* search
                logging.warning(f"No data for chunk ending {current_end_ts}. Retrying in 5s...")
                time.sleep(5) 
        
        # AFTER all attempts for the day/chunk:
        if not day_successful_data_fetch: 
            empty_days += 1
        
        # Move to the previous day/chunk, regardless of success
        current_end_ts = day_start_ts - 1 
        
    # The generator yields the post IDs, but we return the summary data at the very end
    return empty_days, total_days


# ---------- CSV HELPERS ----------
def write_submission_row(w,s,ts):
    """Writes a single row for a post (submission) with its metadata."""
    s_url = getattr(s, "url", "")
    w.writerow([s.id,csv_escape(getattr(s,"title","")),csv_escape(getattr(s,"selftext","")),
                csv_escape(s_url),getattr(getattr(s,"author",None),"name",""),getattr(s,"score",""),ts,
                "","","","","",""])

def write_submission_with_comments(w,s,ts):
    """Writes a post row and then rows for all top-level comments."""
    s_url = getattr(s, "url", "")
    
    # Set sort and replace 'more' links to fetch top-level comments
    s.comment_sort = "confidence"
    
    try:
        # Use replace_more(limit=0) to fetch top-level comments.
        s.comments.replace_more(limit=0)
        
        # CRITICAL FIX: The PRAW comments object (s.comments) must be converted
        # to a flat list to be iterated over reliably when fetching, especially 
        # after calling replace_more().
        comments_list = s.comments.list()
        
    except Exception as e:
        # Handle cases where PRAW fails to process comments (e.g., deleted/locked post)
        logging.warning(f"Failed to fetch comments for post {s.id}: {e}")
        write_submission_row(w,s,ts)
        return

    comments_found = False
    
    # Iterate over the explicitly retrieved list of comments
    for c in comments_list:
        if not hasattr(c, "id"): continue # Skip non-comment objects if any remain
        
        comments_found = True
        
        # Write the row containing both post and comment details
        w.writerow([
            s.id, csv_escape(getattr(s,"title","")), csv_escape(getattr(s,"selftext","")),
            csv_escape(s_url), getattr(getattr(s,"author",None),"name",""), getattr(s,"score",""), ts,
            getattr(c,"id",""), getattr(c,"parent_id",""), csv_escape(getattr(c,"body","")),
            getattr(getattr(c,"author",None),"name",""), getattr(c,"score",""),
            datetime.fromtimestamp(int(getattr(c,"created_utc",0)),tz=timezone.utc).isoformat()
        ])
    
    # If a post has no comments (or after replace_more(limit=0)), still write the post row 
    # to ensure the submission isn't missed in the final CSV.
    if not comments_found:
        write_submission_row(w,s,ts)


# ---------- SCRAPER JOB ----------
def run_scrape_job(job,sub,start_s,end_s,include_comments):
    safe_set(job,state="running",message="Starting…")
    logging.info(f"Job {job}: Starting scrape for {sub} from {start_s} to {end_s}")
    try:
        # Calculate precise start and end timestamps (Unix epoch)
        start=parse_date(start_s)
        end=parse_date(end_s)+timedelta(days=1)-timedelta(microseconds=1) 
        if end<start: raise ValueError("End before start")
        min_ts,max_ts=int(start.timestamp()),int(end.timestamp())
        reddit=make_reddit()
        CAP=LISTING_CAP_WITH_COMMENTS if include_comments else LISTING_CAP_POSTS_ONLY
        
        # Setup temp file for CSV output
        tmp=tempfile.gettempdir()
        fn=os.path.join(tmp,f"{sub}_{start_s}_{end_s}_{int(time.time())}_{job}.csv")
        f=open(fn,"w",newline="",encoding="utf-8")
        w=csv.writer(f); w.writerow([
            "post_id","post_title","post_selftext","post_url","post_author","post_score","post_created_utc",
            "comment_id","comment_parent_id","comment_body","comment_author","comment_score","comment_created_utc"
        ])
        
        count, cap_hit = 0, False
        newest_dt_included, oldest_dt_included = None, None
        
        # Pushshift scraping
        safe_set(job,message="Scraping with Pushshift (daily micro-chunks)…")
        source_label="Pushshift (daily anchored)"
        
        # Initialize the generator and track empty/total days
        gen = iter_pushshift_ids_daily_anchored(sub, min_ts, max_ts, CAP)
        empty_days, total_days = 0, 0
        
        # Iterate over the yielded IDs from the generator
        for sid, cu in gen:
            # We expect the generator to yield the ID and timestamp.
            # The return value (empty_days, total_days) is retrieved after the loop.
            if isinstance(sid, int) and isinstance(cu, int):
                empty_days, total_days = sid, cu
                continue # Skip this if it's the final return value
            
            try:
                # Use PRAW to fetch the full submission data based on the ID from Pushshift
                s=reddit.submission(id=sid)
                dt=datetime.fromtimestamp(int(cu),tz=timezone.utc)
                
                # Track newest/oldest dates
                if newest_dt_included is None: newest_dt_included=dt
                oldest_dt_included=dt
                
                # Write data row
                (write_submission_with_comments if include_comments else write_submission_row)(w,s,dt.isoformat())
                count+=1
                
                # Update progress
                if count%10==0:
                    safe_set(job,progress=min(99,int(count/CAP*100)),
                             message=f"Scraped {count} posts… ({source_label})")
                if count>=CAP: cap_hit=True; break
            except Exception as e:
                logging.warning(f"Job {job}: Failed to fetch submission {sid} from Reddit API: {e}")
        
        # Check the final return of the generator for the empty/total days summary
        if gen and hasattr(gen, 'gi_frame') and gen.gi_frame:
            # Try to get the return value if the loop broke early or finished naturally
            try:
                # The generator is exhausted, we try to call next() to get the return value, which will raise StopIteration
                while True: next(gen)
            except StopIteration as e:
                if e.value and isinstance(e.value, tuple) and len(e.value) == 2:
                    empty_days, total_days = e.value
        
        f.flush(); f.close()
        
        # Format dates for final message
        from_d = newest_dt_included.date().isoformat() if newest_dt_included else "—"
        to_d = oldest_dt_included.date().isoformat() if oldest_dt_included else "—"
        
        # Final success message with statistics
        msg = f"Finished {count} posts. Range: {start_s} → {end_s}. Covered: {to_d} → {from_d}. (Gaps: {empty_days} days of {total_days})"
        logging.info(f"Job {job}: {msg}")
        
        safe_set(job,state="done",progress=100,message=msg,filename=fn,count=count,
                 from_date=from_d,to_date=to_d,cap_hit=cap_hit)
        
    except Exception as e:
        error_msg = f"Job {job} failed: {e}"
        logging.error(error_msg)
        safe_set(job,state="error",message=error_msg)

# ---------- FLASK ROUTES ----------
@app.route("/")
def index(): 
    return render_template("index.html")

@app.post("/start-job")
def start_job():
    sub=request.form.get("subreddit","").strip()
    s=request.form.get("start_date","").strip()
    e=request.form.get("end_date","").strip()
    include_comments=request.form.get("include_comments")=="on"
    if not sub or not s or not e: abort(400,"Missing fields")
    
    try:
        # Validate dates
        start_date = parse_date(s).date()
        end_date = parse_date(e).date()
        if start_date > end_date:
            abort(400, "Start date cannot be after end date.")
    except ValueError:
        abort(400, "Invalid date format. Use YYYY-MM-DD.")
        
    j=uuid.uuid4().hex[:12]
    with JOBS_LOCK: JOBS[j]={"state":"queued","progress":0,"message":"Queued","created_at":time.time()}
    EXECUTOR.submit(run_scrape_job,j,sub,s,e,include_comments)
    return jsonify({"job_id":j})

@app.get("/job-status/<j>")
def job_status(j):
    job=JOBS.get(j)
    if not job: return jsonify({"error":"not_found"}),404
    r={**job}
    if job.get("state")=="done" and job.get("filename"):
        r["download_url"]=url_for("download_job",job_id=j,_external=False)
    return jsonify(r)

@app.get("/download/<job_id>")
def download_job(job_id):
    job=JOBS.get(job_id)
    if not job or job["state"]!="done" or not os.path.exists(job["filename"]): abort(404)
    
    # Generate cleaner download name
    try:
        sub, start_s, end_s = os.path.basename(job["filename"]).split("_")[:3]
    except ValueError:
        sub, start_s, end_s = "reddit", "data", "scrape"
        
    download_name = f"{sub}_{start_s}_to_{end_s}.csv"
    return send_file(job["filename"],mimetype="text/csv",as_attachment=True,
                     download_name=download_name)

@app.after_request
def cleanup(resp):
    """Periodically cleans up old job data and temp files."""
    now=time.time()
    for jid,j in list(JOBS.items()):
        if now-j.get("created_at",now)>JOB_RETENTION_SECONDS:
            fn=j.get("filename")
            if fn and os.path.exists(fn):
                try: os.remove(fn)
                except: logging.error(f"Failed to delete temp file: {fn}")
            JOBS.pop(jid,None)
    return resp

if __name__=="__main__":
    # NOTE: In a production environment, use a proper WSGI server (like Gunicorn)
    # and not Flask's built-in server.
    app.run(host="0.0.0.0",port=5000,debug=True)