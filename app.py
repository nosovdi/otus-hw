from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

api_ver='/api/v1'

# PostgreSQL connection configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'userdb'),
    'user': os.getenv('DB_USER', 'userdb'),
    'password': os.getenv('DB_PASSWORD', 'password'),
    'port': os.getenv('DB_PORT', '5432')
}

# Database connection helper
def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    return conn

# Initialize PostgreSQL database
def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(256) UNIQUE NOT NULL,
                firstName VARCHAR(255),
                lastName VARCHAR(255),
                email VARCHAR(255),
                phone VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        cursor.close()
        conn.close()
        print("Database initialized successfully")
    except Exception as e:
        print(f"Error initializing database: {e}")

# Error response helper
def error_response(message, code=400):
    return jsonify({
        'code': code,
        'message': message
    }), code

# User model to dict conversion
def user_to_dict(user):
    return {
        'id': user['id'],
        'username': user['username'],
        'firstName': user['firstname'],
        'lastName': user['lastname'],
        'email': user['email'],
        'phone': user['phone']
    }

# Routes
@app.route(api_ver+'/user', methods=['POST'])
def create_user():
    data = request.get_json()
    
    # Validate required fields
    if not data or 'username' not in data:
        return error_response('Username is required', 400)
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if username already exists
        cursor.execute(
            'SELECT * FROM users WHERE username = %s', (data['username'],)
        )
        existing_user = cursor.fetchone()
        
        if existing_user:
            return error_response('Username already exists', 409)
        
        # Insert new user
        cursor.execute(
            '''INSERT INTO users (username, firstName, lastName, email, phone)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING *''',
            (data.get('username'), data.get('firstName'), 
             data.get('lastName'), data.get('email'), data.get('phone'))
        )
        
        user = cursor.fetchone()
        conn.commit()
        
        return jsonify(user_to_dict(user)), 201
        
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return error_response('Database error: ' + str(e), 500)
    finally:
        if conn:
            conn.close()

@app.route(api_ver+'/user/<int:user_id>', methods=['GET'])
def get_user(user_id):
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute(
            'SELECT * FROM users WHERE id = %s', (user_id,)
        )
        user = cursor.fetchone()
        
        if user is None:
            return error_response('User not found', 404)
        
        return jsonify(user_to_dict(user))
        
    except psycopg2.Error as e:
        return error_response('Database error: ' + str(e), 500)
    finally:
        if conn:
            conn.close()

@app.route(api_ver+'/user/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    data = request.get_json()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if user exists
        cursor.execute(
            'SELECT * FROM users WHERE id = %s', (user_id,)
        )
        user = cursor.fetchone()
        
        if user is None:
            return error_response('User not found', 404)
        
        # Update user
        cursor.execute(
            '''UPDATE users 
               SET username = %s, firstName = %s, lastName = %s, 
                   email = %s, phone = %s, updated_at = %s
               WHERE id = %s
               RETURNING *''',
            (data.get('username', user['username']),
             data.get('firstName', user['firstname']),
             data.get('lastName', user['lastname']),
             data.get('email', user['email']),
             data.get('phone', user['phone']),
             datetime.now(),
             user_id)
        )
        
        updated_user = cursor.fetchone()
        conn.commit()
        
        return jsonify(user_to_dict(updated_user))
        
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return error_response('Database error: ' + str(e), 500)
    finally:
        if conn:
            conn.close()

@app.route(api_ver+'/user/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    conn = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if user exists
        cursor.execute(
            'SELECT * FROM users WHERE id = %s', (user_id,)
        )
        user = cursor.fetchone()
        
        if user is None:
            return error_response('User not found', 404)
        
        # Delete user
        cursor.execute(
            'DELETE FROM users WHERE id = %s', (user_id,)
        )
        conn.commit()
        
        return '', 204
        
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return error_response('Database error: ' + str(e), 500)
    finally:
        if conn:
            conn.close()

# Health check endpoint
@app.route('/health/', methods=['GET'])
def health_check():
    try:
        conn = get_db_connection()
        conn.close()
        return jsonify({"status": "OK"})
    except:
        return jsonify({"status": "Error, database disconnected"}), 500

if __name__ == '__main__':
#    init_db()
    app.run(debug=True, host='0.0.0.0', port=8000)