import os
import json
import sqlite3
from flask import Flask, request, jsonify, g
from flask_cors import CORS
import requests
from dotenv import load_dotenv
import pandas as pd
from io import StringIO
from datetime import datetime # Import datetime for date handling
from db import get_db_connection, init_db 

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
app = Flask(__name__)
CORS(app) 

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("FATAL ERROR: GEMINI_API_KEY environment variable not set. Check your .env file.")

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent"

# Function to get DB connection on request
def get_db():
    if 'db' not in g:
        g.db = get_db_connection()
    return g.db

# Function to close DB connection when request is done
@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# --- Helper Function for Gemini API Calls (Robust Error Handling) ---

def call_gemini_api(user_prompt, system_instruction=None, is_json=False):
    """Handles the common logic for calling the Gemini API."""
    
    if not GEMINI_API_KEY:
        return {"error": "API Key not configured in the server. Check .env file."}, 500
        
    payload = {
        "contents": [{"parts": [{"text": user_prompt}]}],
    }
    
    # CRITICAL FIX: Add search tool ONLY if NOT requesting JSON
    if not is_json:
        payload["tools"] = [{"google_search": {}}]
    
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    if is_json:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
        }

    # DEBUG: Payload sent to Gemini API
    print("\n--- DEBUG: Payload sent to Gemini API ---")
    print(json.dumps(payload, indent=2))
    print("------------------------------------------")

    headers = {
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(
            f"{API_URL}?key={GEMINI_API_KEY}",
            headers=headers,
            data=json.dumps(payload)
        )
        response.raise_for_status() 
        result = response.json()
        
        generated_content = result.get('candidates')[0]['content']['parts'][0]['text']
        
        return {"content": generated_content}, 200

    except requests.exceptions.HTTPError as e:
        error_details = {"error": f"API call failed: {e.response.status_code} {e.response.reason}"}
        
        # Extract the detailed JSON error message from Google's response body
        try:
            gemini_error_json = response.json()
            error_details["details"] = gemini_error_json.get("error", {}).get("message", "No specific message from API.")
            print(f"\n--- Gemini Detailed Error JSON ---\n{json.dumps(gemini_error_json, indent=2)}\n--- END ERROR ---\n")

            if "API_KEY_INVALID" in error_details["details"] or e.response.status_code == 403:
                 error_details["details"] = "Invalid API Key or API not enabled. Check your .env file and Google Cloud status."
            
        except json.JSONDecodeError:
            error_details["details"] = f"Non-JSON error response from Google API: {response.text[:100]}..."
        except Exception as general_error:
            error_details["details"] = f"Unexpected error during error handling: {general_error}"

        return error_details, e.response.status_code
        
    except Exception as e:
        print(f"Unexpected Python Error: {e}")
        return {"error": f"Internal server error: {str(e)}"}, 500

# --- API Endpoints ---

# POST /api/budget: Generates a JSON budget plan and saves it to DB. (JSON output, NO Search Tool)
@app.route('/api/budget', methods=['POST'])
def generate_budget():
    data = request.get_json()
    income = data.get('income')
    expenses = data.get('expenses')
    goal = data.get('goal')
    
    if not all([income, expenses, goal]):
        return jsonify({"error": "Missing income, expenses, or goal."}), 400

    # 1. Prepare Prompt (System instruction shortened)
    system_instruction = "You are a professional financial engine. Your ONLY response MUST be a complete, valid JSON object strictly following the required schema. Do not include any extra text."
    
    user_prompt = f"Mera monthly income {income} hai, aur monthly fixed expenses {expenses} hain. Mera financial goal {goal} hai. Is data ke aadhar par 50/30/20 rule ka upyog karte hue ek budget aur salah (advice) plan JSON format mein taiyar karein."
    
    # 2. Call Gemini
    response, status = call_gemini_api(user_prompt, system_instruction, is_json=True) 

    if status != 200:
        frontend_error = response.get('details', response.get('error', 'API processing error occurred.'))
        return jsonify({"error": frontend_error}), 500 
    
    try:
        plan_json_str = response['content']
        plan_data = json.loads(plan_json_str) 

        # 3. Save to DB
        db = get_db()
        db.execute(
            "INSERT INTO budgets (income, expenses, goal, plan_json) VALUES (?, ?, ?, ?)",
            (income, expenses, goal, plan_json_str)
        )
        db.commit()

        return jsonify({"message": "Budget plan generated and saved.", "plan": plan_data}), 200
        
    except json.JSONDecodeError:
        print(f"Error decoding JSON from Gemini: {response.get('content')}")
        return jsonify({"error": "AI returned invalid JSON format."}), 500
    except Exception as e:
        print(f"Database/Internal Error: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

# GET /api/budget: Fetches the latest budget plan from DB.
@app.route('/api/budget', methods=['GET'])
def get_budget():
    db = get_db()
    budget = db.execute(
        "SELECT plan_json, created_at FROM budgets ORDER BY id DESC LIMIT 1"
    ).fetchone()
    
    if budget:
        return jsonify({
            "plan": json.loads(budget['plan_json']),
            "created_at": budget['created_at']
        }), 200
    else:
        return jsonify({"message": "No budget plan found."}), 404

# POST /api/chat: Simple chatbot interaction. (Text output, Search Tool is ON)
@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    message = data.get('message')
    
    if not message:
        return jsonify({"error": "Message is required."}), 400

    # 1. Prepare Prompt 
    system_instruction = "You are an AI Financial Advisor for a website user. Give short (max 3 sentences), simple, safe, non-aggressive, and general financial advice responses. Keep the tone helpful and concise."
    user_prompt = message
    
    # 2. Call Gemini
    response, status = call_gemini_api(user_prompt, system_instruction, is_json=False) 

    if status != 200:
        frontend_error = response.get('details', response.get('error', 'API processing error occurred.'))
        return jsonify({"error": frontend_error}), 500

    return jsonify({"reply": response['content']}), 200


# POST /api/upload: Categorizes transactions from CSV and saves them. (JSON output, NO Search Tool)
@app.route('/api/upload', methods=['POST'])
def upload_transactions():
    if 'csv_file' not in request.files:
        return jsonify({"error": "No CSV file part."}), 400
        
    csv_file = request.files['csv_file']
    if csv_file.filename == '':
        return jsonify({"error": "No selected file."}), 400
        
    csv_data = csv_file.read().decode('utf-8')

    # 1. Prepare Prompt 
    system_instruction = "You are a transaction categorization engine. Your ONLY response MUST be a complete, valid JSON object which is an array of categorized transactions. Use only these categories: 'Groceries', 'Rent/EMI', 'Utilities', 'Transport', 'Entertainment', 'Health', 'Savings/Investments', 'Miscellaneous'. DO NOT include any explanatory text."
    user_prompt = f"Please categorize the following raw transactions data:\n\nRaw Data (CSV format):\n{csv_data}"
    
    # 2. Call Gemini
    response, status = call_gemini_api(user_prompt, system_instruction, is_json=True)

    if status != 200:
        frontend_error = response.get('details', response.get('error', 'API processing error occurred.'))
        return jsonify({"error": frontend_error}), 500
    
    try:
        categorized_json_str = response['content']
        categorized_transactions = json.loads(categorized_json_str) 

        # 3. Save to DB
        db = get_db()
        for t in categorized_transactions:
            # FIX: If 'date' is missing or null from AI, use current date to satisfy NOT NULL constraint
            transaction_date = t.get('date') or datetime.now().strftime('%Y-%m-%d')
            transaction_amount = t.get('amount', 0)
            
            # Ensure amount is treated as a float
            try:
                transaction_amount = float(transaction_amount)
            except (ValueError, TypeError):
                transaction_amount = 0.0

            db.execute(
                "INSERT INTO transactions (date, description, amount, category) VALUES (?, ?, ?, ?)",
                (transaction_date, 
                 t.get('description', 'Unknown Description'), 
                 transaction_amount, 
                 t.get('category', 'Miscellaneous'))
            )
        db.commit()

        return jsonify({"message": f"{len(categorized_transactions)} transactions categorized and saved.", "transactions": categorized_transactions}), 200
        
    except json.JSONDecodeError:
        print(f"Error decoding JSON from Gemini: {response.get('content')}")
        return jsonify({"error": "AI returned invalid JSON format."}), 500
    except Exception as e:
        print(f"Database/Internal Error: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

# GET /api/transactions: Retrieves all stored transactions.
@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    db = get_db()
    transactions = db.execute(
        "SELECT id, date, description, amount, category FROM transactions ORDER BY date DESC"
    ).fetchall()
    
    transactions_list = [dict(row) for row in transactions]
    
    return jsonify({"transactions": transactions_list}), 200

# Initialization check
if __name__ == '__main__':
    if not os.path.exists('finance_data.db'):
        init_db()
        
    print("Flask Server running... Navigate to http://127.0.0.1:5000/api/transactions to test API.")
    app.run(debug=True)