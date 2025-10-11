import os
import csv
import time
from io import StringIO
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import praw

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure Reddit client
def get_reddit_client():
    """Initialize and return a Reddit client using PRAW."""
    client_id = os.getenv('REDDIT_CLIENT_ID')
    client_secret = os.getenv('REDDIT_CLIENT_SECRET')
    username = os.getenv('REDDIT_USERNAME')
    password = os.getenv('REDDIT_PASSWORD')
    user_agent = os.getenv('REDDIT_USER_AGENT')
    
    if not all([client_id, client_secret, username, password, user_agent]):
        raise ValueError("Missing Reddit API credentials in environment variables")
    
    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
        user_agent=user_agent
    )

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')

@app.route('/scrape', methods=['POST'])
def scrape():
    """Scrape Reddit posts and comments, return as CSV."""
    try:
        # Get form data
        subreddit_name = request.form.get('subreddit', '').strip()
        days = request.form.get('days', '7')
        
        # Validate inputs
        if not subreddit_name:
            return jsonify({'error': 'Subreddit name is required'}), 400
        
        try:
            days = int(days)
        except ValueError:
            return jsonify({'error': 'Days must be a number'}), 400
        
        if days < 1 or days > 365:
            return jsonify({'error': 'Days must be between 1 and 365'}), 400
        
        # Initialize Reddit client
        try:
            reddit = get_reddit_client()
        except ValueError as e:
            return jsonify({'error': str(e)}), 500
        
        # Create CSV in memory
        output = StringIO()
        csv_writer = csv.writer(output)
        
        # Write CSV headers
        csv_writer.writerow([
            'post_id', 'post_title', 'post_selftext', 'post_author', 
            'post_score', 'post_created_utc', 'comment_id', 
            'comment_parent_id', 'comment_body', 'comment_author', 
            'comment_score', 'comment_created_utc'
        ])
        
        # Calculate cutoff timestamp
        current_time = datetime.now(timezone.utc)
        cutoff_timestamp = current_time.timestamp() - (days * 24 * 60 * 60)
        
        # Fetch subreddit
        try:
            subreddit = reddit.subreddit(subreddit_name)
            # Fetch posts without limit - will iterate until we hit old posts
            posts_generator = subreddit.new(limit=None)
        except Exception as e:
            return jsonify({'error': f'Error accessing subreddit: {str(e)}'}), 400
        
        # Process posts
        posts_scraped = 0
        for post in posts_generator:
            # Check if post is within timeframe
            if post.created_utc < cutoff_timestamp:
                # Once we hit a post older than our timeframe, stop
                break
            
            posts_scraped += 1
            
            # Get post data
            post_id = post.id
            post_title = post.title
            post_selftext = post.selftext
            post_author = str(post.author) if post.author else '[deleted]'
            post_score = post.score
            post_created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc).isoformat()
            
            # Get top-level comments
            try:
                post.comments.replace_more(limit=0)  # Remove "MoreComments" objects
                comments = post.comments.list()
                
                # Filter only top-level comments
                top_level_comments = [c for c in comments if c.parent_id == f't3_{post_id}']
                
                if top_level_comments:
                    for comment in top_level_comments:
                        comment_author = str(comment.author) if comment.author else '[deleted]'
                        comment_created = datetime.fromtimestamp(comment.created_utc, tz=timezone.utc).isoformat()
                        
                        csv_writer.writerow([
                            post_id,
                            post_title,
                            post_selftext,
                            post_author,
                            post_score,
                            post_created,
                            comment.id,
                            comment.parent_id,
                            comment.body,
                            comment_author,
                            comment.score,
                            comment_created
                        ])
                else:
                    # Post with no comments
                    csv_writer.writerow([
                        post_id,
                        post_title,
                        post_selftext,
                        post_author,
                        post_score,
                        post_created,
                        '',
                        '',
                        '',
                        '',
                        '',
                        ''
                    ])
            except Exception as e:
                # If comment retrieval fails, still write post data
                csv_writer.writerow([
                    post_id,
                    post_title,
                    post_selftext,
                    post_author,
                    post_score,
                    post_created,
                    '',
                    '',
                    f'Error fetching comments: {str(e)}',
                    '',
                    '',
                    ''
                ])
            
            # Polite delay to avoid rate limiting
            time.sleep(0.15)
        
        # Get CSV content
        csv_content = output.getvalue()
        output.close()
        
        if posts_scraped == 0:
            return jsonify({'error': f'No posts found in r/{subreddit_name} within the last {days} days'}), 404
        
        # Return CSV data with preview
        preview = csv_content[:5000] if len(csv_content) > 5000 else csv_content
        
        return jsonify({
            'success': True,
            'csv_data': csv_content,
            'preview': preview,
            'filename': f'{subreddit_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv',
            'posts_count': posts_scraped
        })
        
    except Exception as e:
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)