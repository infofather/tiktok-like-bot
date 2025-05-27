import sqlite3
import os
from datetime import datetime


class Database:
    def __init__(self, db_file="tiktok_queue.db"):
        """Initialize database connection"""
        self.db_file = db_file
        self.connection = None
        self.init_db()

    def connect(self):
        """Connect to the SQLite database"""
        self.connection = sqlite3.connect(self.db_file)
        self.connection.row_factory = sqlite3.Row
        return self.connection

    def init_db(self):
        """Initialize database tables if they don't exist"""
        conn = self.connect()
        cursor = conn.cursor()

        # Create users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            likes_given INTEGER DEFAULT 0,
            videos_submitted INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            is_admin INTEGER DEFAULT 0,
            joined_date TEXT,
            last_action TEXT
        )
        ''')

        # Create videos table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tiktok_url TEXT,
            submission_time TEXT,
            status TEXT DEFAULT 'pending',
            likes_count INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')

        # Create likes table to track who liked what
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            video_id INTEGER,
            like_time TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (video_id) REFERENCES videos (id)
        )
        ''')

        # Create settings table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        ''')

        # Create spam_protection table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS spam_protection (
            user_id INTEGER,
            command TEXT,
            timestamp TEXT,
            PRIMARY KEY (user_id, command)
        )
        ''')

        # Insert default settings if they don't exist
        default_settings = [
            ('likes_required', '3'),
            ('points_per_like', '5'),
            ('points_per_submission', '10'),
            ('level_threshold', '50'),
            ('spam_timeout', '5')  # in seconds
        ]
        
        for key, value in default_settings:
            cursor.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )

        conn.commit()
        conn.close()

    # User management methods
    def add_user(self, user_id, username, first_name, last_name):
        """Add a new user to the database"""
        conn = self.connect()
        cursor = conn.cursor()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, joined_date, last_action) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, first_name, last_name, now, now)
        )
        
        conn.commit()
        conn.close()
        
    def get_user(self, user_id):
        """Get user information"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        conn.close()
        return dict(user) if user else None
        
    def update_user_last_action(self, user_id):
        """Update user's last action timestamp"""
        conn = self.connect()
        cursor = conn.cursor()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE users SET last_action = ? WHERE user_id = ?",
            (now, user_id)
        )
        
        conn.commit()
        conn.close()
        
    def increment_user_likes(self, user_id):
        """Increment the number of likes given by a user"""
        conn = self.connect()
        cursor = conn.cursor()
        
        # Get points per like from settings
        cursor.execute("SELECT value FROM settings WHERE key = 'points_per_like'")
        points_per_like = int(cursor.fetchone()['value'])
        
        cursor.execute(
            "UPDATE users SET likes_given = likes_given + 1, points = points + ? WHERE user_id = ?",
            (points_per_like, user_id)
        )
        
        # Check if user should level up
        cursor.execute("SELECT points, level FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        cursor.execute("SELECT value FROM settings WHERE key = 'level_threshold'")
        level_threshold = int(cursor.fetchone()['value'])
        
        new_level = (user['points'] // level_threshold) + 1
        if new_level > user['level']:
            cursor.execute(
                "UPDATE users SET level = ? WHERE user_id = ?",
                (new_level, user_id)
            )
        
        conn.commit()
        conn.close()
        
        return new_level > user['level']  # Return True if user leveled up
        
    def increment_user_submissions(self, user_id):
        """Increment the number of videos submitted by a user"""
        conn = self.connect()
        cursor = conn.cursor()
        
        # Get points per submission from settings
        cursor.execute("SELECT value FROM settings WHERE key = 'points_per_submission'")
        points_per_submission = int(cursor.fetchone()['value'])
        
        cursor.execute(
            "UPDATE users SET videos_submitted = videos_submitted + 1, points = points + ? WHERE user_id = ?",
            (points_per_submission, user_id)
        )
        
        # Check if user should level up
        cursor.execute("SELECT points, level FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        cursor.execute("SELECT value FROM settings WHERE key = 'level_threshold'")
        level_threshold = int(cursor.fetchone()['value'])
        
        new_level = (user['points'] // level_threshold) + 1
        if new_level > user['level']:
            cursor.execute(
                "UPDATE users SET level = ? WHERE user_id = ?",
                (new_level, user_id)
            )
        
        conn.commit()
        conn.close()
        
        return new_level > user['level']  # Return True if user leveled up
        
    def set_admin_status(self, user_id, is_admin):
        """Set or unset admin status for a user"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE users SET is_admin = ? WHERE user_id = ?",
            (1 if is_admin else 0, user_id)
        )
        
        conn.commit()
        conn.close()
        
    def is_admin(self, user_id):
        """Check if a user is an admin"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        
        conn.close()
        return result and result['is_admin'] == 1

    # Video management methods
    def add_video(self, user_id, tiktok_url):
        """Add a new video to the queue"""
        conn = self.connect()
        cursor = conn.cursor()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute(
            "INSERT INTO videos (user_id, tiktok_url, submission_time) VALUES (?, ?, ?)",
            (user_id, tiktok_url, now)
        )
        
        video_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        
        return video_id
        
    def get_video(self, video_id):
        """Get video information by ID"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        video = cursor.fetchone()
        
        conn.close()
        return dict(video) if video else None
        
    def get_queue(self, limit=10, offset=0):
        """Get the current video queue"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT v.*, u.username, u.first_name, u.last_name 
            FROM videos v
            JOIN users u ON v.user_id = u.user_id
            ORDER BY v.submission_time ASC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        
        queue = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return queue
        
    def update_video_status(self, video_id, status):
        """Update the status of a video"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE videos SET status = ? WHERE id = ?",
            (status, video_id)
        )
        
        conn.commit()
        conn.close()
        
    def delete_video(self, video_id):
        """Delete a video from the queue"""
        conn = self.connect()
        cursor = conn.cursor()
        
        # First delete any likes associated with this video
        cursor.execute("DELETE FROM likes WHERE video_id = ?", (video_id,))
        
        # Then delete the video
        cursor.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        
        conn.commit()
        conn.close()

    # Like management methods
    def add_like(self, user_id, video_id):
        """Record a like from a user for a video"""
        conn = self.connect()
        cursor = conn.cursor()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Check if the user has already liked this video
        cursor.execute(
            "SELECT id FROM likes WHERE user_id = ? AND video_id = ?",
            (user_id, video_id)
        )
        
        if cursor.fetchone():
            conn.close()
            return False  # User already liked this video
        
        # Add the like
        cursor.execute(
            "INSERT INTO likes (user_id, video_id, like_time) VALUES (?, ?, ?)",
            (user_id, video_id, now)
        )
        
        # Update the likes count for the video
        cursor.execute(
            "UPDATE videos SET likes_count = likes_count + 1 WHERE id = ?",
            (video_id,)
        )
        
        conn.commit()
        conn.close()
        
        return True
        
    def get_user_likes(self, user_id):
        """Get all videos liked by a user"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT v.id, v.tiktok_url, l.like_time
            FROM likes l
            JOIN videos v ON l.video_id = v.id
            WHERE l.user_id = ?
            ORDER BY l.like_time DESC
        """, (user_id,))
        
        likes = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return likes
        
    def has_liked_video(self, user_id, video_id):
        """Check if a user has liked a specific video"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT id FROM likes WHERE user_id = ? AND video_id = ?",
            (user_id, video_id)
        )
        
        result = cursor.fetchone() is not None
        
        conn.close()
        return result

    # Settings methods
    def get_setting(self, key):
        """Get a setting value by key"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = cursor.fetchone()
        
        conn.close()
        return result['value'] if result else None
        
    def update_setting(self, key, value):
        """Update a setting value"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE settings SET value = ? WHERE key = ?",
            (value, key)
        )
        
        conn.commit()
        conn.close()

    # Spam protection methods
    def record_command(self, user_id, command):
        """Record a command execution for spam protection"""
        conn = self.connect()
        cursor = conn.cursor()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute(
            "INSERT OR REPLACE INTO spam_protection (user_id, command, timestamp) VALUES (?, ?, ?)",
            (user_id, command, now)
        )
        
        conn.commit()
        conn.close()
        
    def can_execute_command(self, user_id, command):
        """Check if a user can execute a command (spam protection)"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM settings WHERE key = 'spam_timeout'")
        timeout = int(cursor.fetchone()['value'])
        
        cursor.execute(
            "SELECT timestamp FROM spam_protection WHERE user_id = ? AND command = ?",
            (user_id, command)
        )
        
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return True
        
        last_execution = datetime.strptime(result['timestamp'], "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        
        time_diff = (now - last_execution).total_seconds()
        
        conn.close()
        return time_diff > timeout
        
    def get_likes_required(self):
        """Get the number of likes required to submit a video"""
        return int(self.get_setting('likes_required'))
        
    def can_submit_video(self, user_id):
        """Check if a user can submit a video based on likes given"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute("SELECT likes_given FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        likes_required = self.get_likes_required()
        
        conn.close()
        return user and user['likes_given'] >= likes_required
