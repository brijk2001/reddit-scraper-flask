# Reddit Scraper - Flask + Bootstrap Web App

A complete, beginner-friendly web application that scrapes Reddit posts and comments using Python, Flask, and Bootstrap 5. Download your data as CSV files instantly!

> **Runs in PullPush-only mode — no Reddit API credentials required.**
> Reddit disabled self-serve API key creation in late 2025 (their [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)), so this app pulls posts and comments from the public [PullPush](https://pullpush.io) mirror (a Pushshift archive) instead. You can run it immediately, with zero credentials.

## 🚀 Features

- ✅ Modern Bootstrap 5 interface
- ✅ Scrape any public subreddit
- ✅ **No Reddit account or API credentials needed**
- ✅ Filter by a **date range** (start/end date)
- ✅ Optional **keyword filtering** (comma-separated)
- ✅ Include or exclude comments
- ✅ Export to CSV with one click
- ✅ Mobile-responsive design
- ✅ Ready for Render/Railway/Heroku deployment

---

## ⚠️ Important: Data Coverage Limits

Because this build uses the PullPush mirror rather than Reddit's live API, keep two things in mind:

1. **PullPush ingestion lags real-time.** Recent posts (currently anything after roughly **mid-2025**) may return little or no data. For reliable results, choose date ranges that are at least several months in the past. When a range has no data, the app reports `Sources: [No data found]`.
2. **PullPush rate-limits aggressively.** The app automatically backs off on `429` responses. Comments mode is noticeably slower because it makes an extra request per post — posts-only is much faster.

To scrape recent data or lift these limits, you'll need **official Reddit API access**, which now requires a manual approval process (typically 2–4 weeks). See [Restoring the Reddit API](#-optional-restoring-the-reddit-api) below.

---

## 📋 Prerequisites

Before you begin, make sure you have:

1. **Python 3.10 or higher** installed ([Download here](https://www.python.org/downloads/))
2. That's it — no Reddit account or API keys needed for PullPush-only mode.

---

## 💻 Step 1: Local Setup

### 1.1 Download the Project

Clone or download this repository to your computer:

```bash
git clone https://github.com/brijk2001/reddit-scraper-flask.git
cd reddit-scraper-flask
```

The folder structure looks like this:

```
reddit-scraper-flask/
├── app.py
├── requirements.txt
├── .env
├── Procfile
└── templates/
    └── index.html
```

### 1.2 Create a Virtual Environment

Open your terminal/command prompt in the project folder:

**On Windows:**

```bash
python -m venv .venv
.venv\Scripts\activate
```

**On Mac/Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` at the start of your terminal line.

### 1.3 Install Dependencies

```bash
pip install -r requirements.txt
```

This installs Flask, requests, python-dotenv, PRAW, and gunicorn. (PRAW is only needed if you later re-enable the official Reddit API — see below.)

---

## 🔐 Step 2: Configure the Environment File

Create a file named `.env` in the project root (same folder as `app.py`). For PullPush-only mode, the **only** value used is a user-agent string sent as a header to PullPush:

```env
# PullPush-only mode: NO Reddit credentials required.
REDDIT_USER_AGENT=reddit-scraper/0.1 by u/your_reddit_username

# --- For LATER, once Reddit approves your API app (reddit.com/prefs/apps) ---
# REDDIT_CLIENT_ID=
# REDDIT_CLIENT_SECRET=
```

Optional tuning variables (all have sensible defaults):

| Variable                   | Default                        | Purpose                                    |
| -------------------------- | ------------------------------ | ------------------------------------------ |
| `PUSHSHIFT_BASE_URLS`      | `https://api.pullpush.io/...`  | Comma-separated mirror URLs                |
| `PULLPUSH_COMMENT_URL`     | `https://api.pullpush.io/...`  | PullPush comment endpoint                  |
| `DAILY_CHUNK_SECONDS`      | `86400`                        | Pagination window size (seconds)           |
| `PUSHSHIFT_PAGE_SIZE`      | `100`                          | Results per PullPush request               |
| `PUSHSHIFT_MAX_RETRIES`    | `4`                            | Retries per request on error/429           |
| `PUSHSHIFT_REQUEST_TIMEOUT`| `30`                           | Request timeout (seconds)                  |

---

## 🏃 Step 3: Run Locally

Start the Flask development server:

```bash
python app.py
```

You should see output like:

```
 * Running on http://0.0.0.0:5000
 * Debug mode: on
```

Open your browser and visit: **http://localhost:5000**

🎉 You should see the Reddit Scraper interface!

### Testing the App

1. Enter a subreddit name (e.g., `python`, `technology`, `news`)
2. Choose a **start date** and **end date** (pick a range at least several months in the past for best results, e.g. `2025-01-01` to `2025-01-07`)
3. Optionally enter comma-separated **keywords** to filter posts
4. Optionally check **Include comments**
5. Click **"Start Scraping"**
6. Watch the live progress, then download the CSV when it completes

---

## 🌐 Step 4: Deploy to the Cloud

Deploy your app to make it accessible online. Since no Reddit credentials are needed, deployment is simpler — you only need to (optionally) set `REDDIT_USER_AGENT`.

### Option A: Deploy to Render (Recommended - Free Tier)

1. **Push your code to GitHub:**

   ```bash
   git add .
   git commit -m "Deploy reddit scraper"
   git push origin main
   ```

2. **Create a Render account:** [https://render.com](https://render.com)

3. **Create a new Web Service:**

   - Click **"New +"** → **"Web Service"**
   - Connect your GitHub repository and select `reddit-scraper-flask`

4. **Configure the service:**

   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Instance Type**: Free

5. **(Optional) Add Environment Variables** under the **"Environment"** tab:
   - `REDDIT_USER_AGENT` — a descriptive user-agent string

6. **Deploy:** Click **"Create Web Service"** and wait a few minutes.

### Option B: Deploy to Railway

1. Push your code to GitHub (same as above)
2. Create a Railway account: [https://railway.app](https://railway.app)
3. **"New Project"** → **"Deploy from GitHub repo"** → select your repo (Railway auto-detects Python)
4. (Optional) add `REDDIT_USER_AGENT` under the **"Variables"** tab
5. **"Settings"** → **"Generate Domain"** to get a public URL

### Option C: Deploy to Heroku

```bash
heroku login
heroku create reddit-scraper-yourname
heroku config:set REDDIT_USER_AGENT="reddit-scraper/0.1 by u/yourname"  # optional
git push heroku main
heroku open
```

---

## 📊 CSV Output Format

Your downloaded CSV file will have these columns:

| Column                | Description                |
| --------------------- | -------------------------- |
| `post_id`             | Reddit post ID             |
| `post_title`          | Title of the post          |
| `post_selftext`       | Body text of the post      |
| `post_url`            | URL of the post            |
| `post_author`         | Username of poster         |
| `post_score`          | Upvotes minus downvotes    |
| `post_created_utc`    | Timestamp (ISO format)     |
| `comment_id`          | Comment ID (if applicable) |
| `comment_parent_id`   | Parent ID                  |
| `comment_body`        | Comment text               |
| `comment_author`      | Commenter username         |
| `comment_score`       | Comment score              |
| `comment_created_utc` | Comment timestamp          |

When comments are included, each row contains a post + one of its comments. Posts without comments (or when comments are excluded) produce one row with empty comment fields.

---

## 🐛 Troubleshooting

### Problem: "No posts found" / `Sources: [No data found]`

**Solution:**

- Your date range may be **too recent** — PullPush lags behind real-time, so pick a range further in the past (several months or more).
- Try a busier subreddit like `r/python`, `r/AskReddit`, or `r/technology`.
- Widen the date range.

### Problem: Scraping is very slow

**Solution:**

- **Comments mode is slow** — it fetches comments per post with a pause plus PullPush rate-limit backoff. Uncheck **Include comments** for much faster posts-only runs.
- PullPush returns `429 Too Many Requests` under load; the app automatically waits and retries.

### Problem: "429 Too Many Requests" in the logs

**Solution:**

- This is PullPush rate-limiting and is handled automatically with exponential backoff. Just let it run — no action needed.

### Problem: CSV download doesn't start

**Solution:**

- Check your browser's download settings (allow pop-ups).
- Open the browser console (F12) to check for JavaScript errors.
- Try a different browser.

### Problem: App crashes after 30 seconds on Render/Railway free tier

**Solution:**

- Free tiers have request timeouts. Jobs run in a background thread with polling, so the initial request returns quickly — but very large ranges with comments can still be slow. Narrow the date range or disable comments.

### Problem: Module not found errors

**Solution:**

```bash
pip install --upgrade pip
pip install -r requirements.txt --force-reinstall
```

### Problem: Port already in use (Windows)

**Solution:**

```bash
# Find process using port 5000
netstat -ano | findstr :5000

# Kill that process (replace PID)
taskkill /PID <process_id> /F
```

---

## 🔮 (Optional) Restoring the Reddit API

PullPush-only mode is great for historical data, but it can't provide recent posts. To scrape recent data, you need official Reddit API access:

1. Apply for API access via Reddit's developer process (subject to their [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy) — approval typically takes 2–4 weeks).
2. Once approved, create a **"script"** app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) and copy the **client ID** and **secret**.
3. Paste them into the commented `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` lines in `.env`.

The code keeps a ready-to-use `make_reddit()` helper (read-only PRAW client) for wiring the official API back in for recent data.

---

## 🔒 Security Notes

- **Never commit your `.env` file to GitHub!** It's already listed in `.gitignore`.
- On deployed platforms, set values as environment variables (not hardcoded).
- Respect Reddit's Terms of Service and PullPush's usage — scrape only public subreddits and keep request volumes reasonable.

---

## 📚 How It Works

1. **Frontend (Bootstrap 5):** User enters a subreddit, date range, optional keywords, and a comments toggle.
2. **Flask Backend:** Receives the form via POST and starts a background job (ThreadPoolExecutor). The browser polls `/job-status/<id>` for live progress.
3. **PullPush (Pushshift mirror):** The scraper walks the date range day-by-day with anchored pagination to pull full post data (title, body, author, score, URL), bypassing Reddit's 1,000-post listing limit.
4. **Comments:** If enabled, comments are fetched per post from PullPush's comment endpoint.
5. **Filtering:** Posts outside the date range or not matching the keywords are skipped.
6. **CSV Export:** Results are written to a CSV and served via `/download/<id>`. Old jobs and temp files are cleaned up automatically after an hour.
