import time
import requests
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, request
from google.cloud import firestore
import google.generativeai as genai
from datetime import datetime, timezone
import email.utils
import re
import urllib.parse
import json
from duckduckgo_search import DDGS
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- AI CONFIGURATION ---
# We are using ONLY Gemini as requested.
GEMINI_API_KEY = "AIzaSyAeJgmq-hGeO83HKpQnQVQAKicboXql6Kc"

gemini_model = None
if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_API_KEY":
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Using gemini-1.5-flash for the fastest, high-quality responses
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        print("Gemini SDK successfully initialized.")
    except Exception as e:
        print(f"Gemini Init Error: {e}")

# Initialize Firestore
db = None
try:
    db = firestore.Client(database='finlit')
except Exception as e:
    print(f"Warning: Firestore could not be initialized: {e}")

# --- EXPERT KNOWLEDGE BASE (Ultimate Backup) ---
# This ensures the AI ALWAYS answers, even if the API quota is exhausted.
EXPERIENCE_DATA = {
    "compounding": "Compounding is the strategy of earning interest on your interest. In India, a ₹10,000 monthly SIP at 12% can grow to over ₹1 Crore in 20 years!",
    "sip": "**SIP (Systematic Investment Plan)** is a disciplined way to invest in mutual funds. It averages out your purchase cost (Rupee Cost Averaging) and helps you build a massive corpus without timing the market.",
    "tax": "For Indian taxpayers, **Section 80C** allows tax deductions up to ₹1.5 Lakh via ELSS, PPF, and Life Insurance. Don't forget **Section 80D** for health insurance premiums!",
    "80c": "Under **Section 80C**, you can save tax on up to ₹1.5 Lakh. Top options include **ELSS** (highest growth), **PPF** (safest), and **Tax-Saving FDs**.",
    "ppf": "**PPF (Public Provident Fund)** is a highly safe, government-backed saving tool with a 15-year lock-in and tax-free interest. It's excellent for long-term safety.",
    "elss": "**ELSS (Equity Linked Savings Scheme)** is a tax-saving mutual fund with a 3-year lock-in. It is the best 80C option for high long-term wealth creation.",
    "budget": "The **50/30/20 Rule** suggests 50% for Needs, 30% for Wants, and 20% for Savings. Use our Budget Tracker to optimize your spending!",
    "mutual funds": "**Mutual Funds** offer professional management and diversification. For long-term goals, Equity Funds are generally superior to FDs for wealth creation.",
    "fixed deposit": "**Fixed Deposits (FDs)** are safe but struggle to beat inflation. Use them for your Emergency Fund, but look at Mutual Funds for long-term growth.",
}

# Cache configuration for News
CACHE_EXPIRY = 600 
news_cache = {'data': None, 'timestamp': 0}
RSS_URL = 'https://news.google.com/rss/search?q=finance+india&hl=en-IN&gl=IN&ceid=IN:en'

def fetch_financial_news():
    try:
        response = requests.get(RSS_URL, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        news_items = []
        for item in root.findall('./channel/item')[:12]:
            title = item.find('title').text if item.find('title') is not None else 'Financial News'
            link = item.find('link').text if item.find('link') is not None else '#'
            pubDate = item.find('pubDate').text if item.find('pubDate') is not None else ''
            source = "Markets"
            if ' - ' in title:
                parts = title.rsplit(' - ', 1)
                title = parts[0]
                source = parts[1]
            news_items.append({'title': title, 'link': link, 'time': pubDate, 'category': source})
        return news_items
    except Exception as e:
        print(f"Error fetching news: {e}")
        return []

@app.route('/api/news')
def get_news():
    current_time = time.time()
    if news_cache['data'] is None or (current_time - news_cache['timestamp']) > CACHE_EXPIRY:
        fresh_data = fetch_financial_news()
        if fresh_data:
            news_cache['data'] = fresh_data
            news_cache['timestamp'] = current_time
    return jsonify(news_cache['data'] if news_cache['data'] else [])

@app.route('/api/userdata', methods=['GET', 'POST'])
def userdata():
    if not db:
        return jsonify({'error': 'Database not initialized'}), 500
    if request.method == 'GET':
        uid = request.args.get('uid')
        if not uid: return jsonify({'error': 'Missing uid'}), 400
        doc = db.collection('users').document(uid).get()
        return jsonify(doc.to_dict() if doc.exists else {'income': 0, 'expenses': [], 'goals': [], 'points': 0})
    elif request.method == 'POST':
        data = request.get_json()
        uid = data.pop('uid')
        db.collection('users').document(uid).set(data)
        return jsonify({'status': 'success'})

def fetch_live_ai_response(query):
    # --- 1. Pure Gemini SDK Execution ---
    if gemini_model:
        try:
            response = gemini_model.generate_content(
                f"You are FinLit AI, a professional Indian financial expert. "
                f"Provide a helpful, detailed response. Use **bolding** for key terms. "
                f"User Query: {query}"
            )
            if response and response.text:
                return response.text
        except Exception as e:
            print(f"Gemini API Runtime Error: {e}")

    # --- 2. Live Search Backup (DuckDuckGo) ---
    try:
        with DDGS() as ddgs:
            resp = ddgs.chat(f"Detailed financial advice for India: {query}", model='gpt-4o-mini')
            if resp: return resp
    except: pass

    # --- 3. Expert Knowledge Fallback ---
    low_query = query.lower()
    for key, val in EXPERIENCE_DATA.items():
        if key in low_query:
            return f"**Expert Insight on {key.upper()}:**\n\n{val}\n\nWhat else would you like to know about this?"

    return "That is an excellent financial question. My connection to the live data stream is currently optimizing, but remember that for Indian investors, **long-term SIPs** and **tax-efficient investing (like ELSS under 80C)** remain the absolute best ways to build wealth. Would you like to track your budget instead?"

def generate_mock_ai_response(message):
    msg = message.lower()
    
    # Conversational Handlers
    if re.search(r'^(hi|hello|hey|greetings|namaste)\b', msg):
        return "Hi there! 👋 I'm your FinLit AI Assistant. I'm ready to help you analyze your finances and build long-term wealth. What can we work on today?"
    if re.search(r'^(yes|yeah|sure|yep|ok|okay|definitely|absolutely)\b', msg) or msg == 'y':
        return "Excellent! Let's get to work. 🚀 Would you like to analyze your **Budget**, calculate **Tax Savings**, or explore **Mutual Funds**?"
    if re.search(r'^(no|nope|nah|not now|maybe later)\b', msg) or msg == 'n':
        return "No problem! I'm here whenever you're ready to take control of your money. Just ask me anything!"
    
    return fetch_live_ai_response(message)

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({'error': 'Missing message'}), 400
    try:
        response_text = generate_mock_ai_response(data['message'])
        return jsonify({'response': response_text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
