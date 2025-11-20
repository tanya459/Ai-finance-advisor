import sqlite3
import os

# Database file path
DB_FILE = 'finance_data.db'

def get_db_connection():
    """Returns a new connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    return conn

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Transactions Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL
        )
    ''')
    
    # 2. Budgets Table (to store the generated JSON budget plans)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            income REAL NOT NULL,
            expenses REAL NOT NULL,
            goal TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"Database '{DB_FILE}' initialized successfully.")

if __name__ == '__main__':
    # Check if the database file exists to avoid re-initializing if data is present
    if not os.path.exists(DB_FILE):
        init_db()
    else:
        print(f"Database '{DB_FILE}' already exists. Skipping initialization.")
        # Optionally, you can call init_db() to ensure tables exist without deleting data
        init_db()