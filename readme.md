# Reddit Scraper - Flask + Bootstrap Web App

A complete, beginner-friendly web application that scrapes Reddit posts and comments using Python, Flask, PRAW, and Bootstrap 5. Download your data as CSV files instantly!

## 🚀 Features

- ✅ Modern Bootstrap 5 interface
- ✅ Scrape any public subreddit
- ✅ Filter by timeframe (days)
- ✅ Limit number of posts
- ✅ Export to CSV with one click
- ✅ Live preview of scraped data
- ✅ Mobile-responsive design
- ✅ Ready for Render/Railway/Heroku deployment

---

## 📋 Prerequisites

Before you begin, make sure you have:

1. **Python 3.10 or higher** installed ([Download here](https://www.python.org/downloads/))
2. A **Reddit account**
3. **Reddit API credentials** (we'll get these in Step 1)

---

## 🔑 Step 1: Get Reddit API Credentials

You need to register your app with Reddit to get API access:

1. Go to [https://www.reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Scroll to the bottom and click **"create another app..."**
3. Fill in the form:
   - **name**: `reddit-scraper` (or any name you like)
   - **App type**: Select **"script"**
   - **description**: Leave blank
   - **about url**: Leave blank
   - **redirect uri**: Enter `http://localhost:8080` (required but not used)
4. Click **"create app"**
5. You'll see your app details:
   - **CLIENT_ID**: The string under "personal use script" (14 characters)
   - **CLIENT_SECRET**: The string next to "secret" (27 characters)

Save these values—you'll need them in Step 3!

---

## 💻 Step 2: Local Setup

### 2.1 Download the Project

Clone or download this repository to your computer:

```bash
git clone https://github.com/yourusername/reddit-scraper-flask.git
cd reddit-scraper-flask
```

Or manually create the folder structure:

```
reddit-scraper-flask/
├── app.py
├── requirements.txt
├── .env
├── Procfile
└── templates/
    └── index.html
```

### 2.2 Create a Virtual Environment

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

### 2.3 Install Dependencies

```bash
pip install -r requirements.txt
```

This installs Flask, PRAW, python-dotenv, and gunicorn.

---

## 🔐 Step 3: Configure Environment Variables

1. Create a file named `.env` in the project root (same folder as `app.py`)
2. Copy the contents from `.env.example`
3. Replace the placeholder values with your actual Reddit credentials:

```env
REDDIT_CLIENT_ID=your_14_char_client_id
REDDIT_CLIENT_SECRET=your_27_char_secret
REDDIT_USERNAME=your_reddit_username
REDDIT_PASSWORD=your_reddit_password
REDDIT_USER_AGENT=reddit-scraper/0.1 by u/your_reddit_username
```

**Important:**

- Use your actual Reddit username and password
- The `REDDIT_USER_AGENT` should include your Reddit username (e.g., `by u/john_doe`)
- Never share your `.env` file or commit it to GitHub!

---

## 🏃 Step 4: Run Locally

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
2. Set timeframe (e.g., `7` days)
3. Set limit (e.g., `50` posts)
4. Click **"Start Scraping"**
5. Wait for the scraping to complete (15-30 seconds)
6. Your CSV will automatically download
7. View the preview at the bottom of the page

---

## 🌐 Step 5: Deploy to the Cloud

Deploy your app to make it accessible online. Here are instructions for three popular platforms:

### Option A: Deploy to Render (Recommended - Free Tier)

1. **Push your code to GitHub:**

   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/yourusername/reddit-scraper-flask.git
   git push -u origin main
   ```

2. **Create a Render account:** [https://render.com](https://render.com)

3. **Create a new Web Service:**

   - Click **"New +"** → **"Web Service"**
   - Connect your GitHub repository
   - Select your `reddit-scraper-flask` repo

4. **Configure the service:**

   - **Name**: `reddit-scraper` (or any name)
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Instance Type**: Free

5. **Add Environment Variables:**

   - Click **"Environment"** tab
   - Add each variable from your `.env` file:
     - `REDDIT_CLIENT_ID`
     - `REDDIT_CLIENT_SECRET`
     - `REDDIT_USERNAME`
     - `REDDIT_PASSWORD`
     - `REDDIT_USER_AGENT`

6. **Deploy:**
   - Click **"Create Web Service"**
   - Wait 2-3 minutes for deployment
   - Your app will be live at `https://reddit-scraper-xxxx.onrender.com`

### Option B: Deploy to Railway

1. **Push code to GitHub** (same as above)

2. **Create Railway account:** [https://railway.app](https://railway.app)

3. **Deploy:**

   - Click **"New Project"** → **"Deploy from GitHub repo"**
   - Select your repo
   - Railway auto-detects Python and deploys

4. **Add Environment Variables:**

   - Go to your project → **"Variables"** tab
   - Add all Reddit credentials

5. **Access your app:**
   - Click **"Settings"** → **"Generate Domain"**
   - Your app is live!

### Option C: Deploy to Heroku

1. **Install Heroku CLI:** [https://devcenter.heroku.com/articles/heroku-cli](https://devcenter.heroku.com/articles/heroku-cli)

2. **Login and create app:**

   ```bash
   heroku login
   heroku create reddit-scraper-yourname
   ```

3. **Set environment variables:**

   ```bash
   heroku config:set REDDIT_CLIENT_ID=your_client_id
   heroku config:set REDDIT_CLIENT_SECRET=your_secret
   heroku config:set REDDIT_USERNAME=your_username
   heroku config:set REDDIT_PASSWORD=your_password
   heroku config:set REDDIT_USER_AGENT="reddit-scraper/0.1 by u/yourname"
   ```

4. **Deploy:**
   ```bash
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
| `post_author`         | Username of poster         |
| `post_score`          | Upvotes minus downvotes    |
| `post_created_utc`    | Timestamp (ISO format)     |
| `comment_id`          | Comment ID (if applicable) |
| `comment_parent_id`   | Parent post ID             |
| `comment_body`        | Comment text               |
| `comment_author`      | Commenter username         |
| `comment_score`       | Comment score              |
| `comment_created_utc` | Comment timestamp          |

Each row contains a post + one of its top-level comments. Posts without comments will have one row with empty comment fields.

---

## 🐛 Troubleshooting

### Problem: "Missing Reddit API credentials"

**Solution:**

- Make sure your `.env` file exists in the same folder as `app.py`
- Double-check that all 5 environment variables are filled in
- Restart the Flask app after editing `.env`

### Problem: "Error accessing subreddit: Forbidden"

**Solution:**

- Your Reddit account may need to verify email
- Wait 5-10 minutes after creating API credentials
- Check if the subreddit is private (you can only scrape public subreddits)
- Try a well-known subreddit like `python` or `news`

### Problem: "429 Too Many Requests"

**Solution:**

- Reddit rate limits API calls
- The app includes a 0.15-second delay between posts
- If you hit limits, wait 5-10 minutes before trying again
- Reduce your post limit to 50 or less

### Problem: CSV download doesn't start

**Solution:**

- Check browser's download settings (allow pop-ups)
- Open browser console (F12) to see any JavaScript errors
- Try a different browser (Chrome, Firefox, Safari)

### Problem: "No posts found" despite subreddit being active

**Solution:**

- Your timeframe might be too restrictive (try 30 days instead of 7)
- The subreddit might be slow (try `r/python` or `r/technology`)
- Some posts might be filtered by Reddit's spam filter

### Problem: App crashes after 30 seconds on Render/Railway

**Solution:**

- Free tier platforms have 30-second request timeouts
- Reduce post limit to 25-50
- Scraping is I/O bound; larger limits need paid tiers

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

## 🔒 Security Notes

- **Never commit your `.env` file to GitHub!** Add it to `.gitignore`:
  ```bash
  echo ".env" >> .gitignore
  ```
- Use environment variables on deployed platforms (not hardcoded credentials)
- Be careful with Reddit accounts—don't share your password
- This app uses your account; respect Reddit's Terms of Service
- Don't scrape private or NSFW subreddits without proper authentication

---

## 📚 How It Works

1. **Frontend (Bootstrap 5):** User enters subreddit, timeframe, and limit
2. **Flask Backend:** Receives form data via POST request
3. **PRAW Library:** Authenticates with Reddit API using your credentials
4. **Data Collection:** Fetches recent posts from specified subreddit
5. **Filtering:** Only includes posts within the timeframe
6. **Comment Extraction:** Gets top
