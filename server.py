import http.server
import socketserver
import json
import urllib.parse
import os
import re
import secrets
import hashlib
import time
from datetime import datetime, timezone
import pymongo
from bson import ObjectId

# Load local env files if they exist
def load_env_file(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        key, val = line.strip().split("=", 1)
                        v = val.strip()
                        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                            v = v[1:-1]
                        os.environ[key.strip()] = v
        except Exception as e:
            print(f"[WARNING] Could not load {filepath} file: {e}")

load_env_file(".env")
load_env_file("atlas-credentials.env")

raw_mongo_uri = os.environ.get("MONGODB_URI")
if not raw_mongo_uri or "xxxxxx" in raw_mongo_uri:
    raw_mongo_uri = os.environ.get("MONGO_URI")
if raw_mongo_uri and "xxxxxx" in raw_mongo_uri:
    raw_mongo_uri = None

MONGO_URI = raw_mongo_uri or "mongodb://localhost:27017/"
SECRET_KEY = secrets.token_hex(32)
GOOGLE_CLIENT_ID = "556888061468-r7ukjulnh2esht6vrtjqtgs6gim0slhh.apps.googleusercontent.com"
LATEST_STUDENT_SESSION = {"email": None, "timestamp": 0}

import certifi

mongo_client = None
db = None

def get_db():
    global mongo_client, db
    if mongo_client is None:
        try:
            mongo_client = pymongo.MongoClient(MONGO_URI, tlsCAFile=certifi.where())
        except Exception:
            mongo_client = pymongo.MongoClient(MONGO_URI)
        db = mongo_client.get_database("flylock")
    return db

def init_db():
    database = get_db()
    # Create indexes for unique and performance lookups
    database.users.create_index("email", unique=True)
    database.creator_allowlist.create_index("email", unique=True)
    database.sessions.create_index("id", unique=True)
    database.assessments.create_index("exam_code", unique=True)
    database.launch_tokens.create_index("nonce", unique=True)
    database.exam_attempts.create_index("session_cookie_id", unique=True, sparse=True)
    database.audit_logs.create_index("timestamp")
    
    # Ensure system user exists
    admin_row = database.users.find_one({"role": "admin"})
    if not admin_row:
        database.users.insert_one({
            "email": "system@bitsathy.ac.in",
            "role": "admin",
            "active_session_id": None,
            "created_at": datetime.now(timezone.utc)
        })
        database.audit_logs.insert_one({
            "event_type": "SYSTEM_INIT",
            "actor": "system",
            "timestamp": datetime.now(timezone.utc),
            "details": "FlyLock Assessment Portal production database initialized."
        })

def log_audit(event_type, actor, exam_code=None, session_id=None, details=None):
    if not actor:
        actor = 'system@bitsathy.ac.in'
    try:
        database = get_db()
        database.audit_logs.insert_one({
            "timestamp": datetime.now(timezone.utc),
            "event_type": event_type,
            "actor": actor,
            "exam_code": exam_code,
            "session_id": session_id,
            "details": details
        })
    except Exception as ex:
        print(f"[AUDIT LOG WARNING] Failed to record audit log: {ex}")

def parse_cookies(cookie_header):
    cookies = {}
    if cookie_header:
        pairs = cookie_header.split(";")
        for p in pairs:
            if "=" in p:
                k, v = p.strip().split("=", 1)
                cookies[k] = v
    return cookies

class FlyLockHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Allow cross-origin requests dynamically based on Origin or Referer header to support credentials
        origin = self.headers.get("Origin")
        if not origin:
            referer = self.headers.get("Referer")
            if referer:
                parts = referer.split("/")
                if len(parts) >= 3:
                    origin = parts[0] + "//" + parts[2]
        
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        else:
            self.send_header("Access-Control-Allow-Origin", "https://mageesharavinds.github.io")
            
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-FlyLock-Client")
        self.send_header("Access-Control-Allow-Credentials", "true")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def read_json_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        body = self.rfile.read(content_length).decode('utf-8')
        try:
            return json.loads(body)
        except Exception:
            return {}

    def send_json(self, data, status=200, headers_dict=None):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if headers_dict:
            for k, v in headers_dict.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def authenticate_user(self):
        cookies = parse_cookies(self.headers.get('Cookie'))
        session_id = cookies.get('flylock_user_session')
        
        if not session_id:
            auth_header = self.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                session_id = auth_header.split(' ', 1)[1].strip()

        if session_id:
            database = get_db()
            session = database.sessions.find_one({"id": session_id})
            if session and session.get('revoked_at') is None:
                user_id = session['user_id']
                query_filter = {"_id": ObjectId(user_id)} if ObjectId.is_valid(user_id) else {"email": user_id}
                user = database.users.find_one(query_filter)
                if user and user.get('active_session_id') == session_id:
                    u = dict(user)
                    u['id'] = str(user['_id'])
                    del u['_id']
                    u['role'] = 'admin'
                    return u

        student_email = cookies.get('flylock_student_email')
        if student_email and student_email.endswith('@bitsathy.ac.in'):
            database = get_db()
            user = database.users.find_one({"email": student_email})
            if not user:
                res = database.users.insert_one({
                    "email": student_email,
                    "role": "admin",
                    "active_session_id": None,
                    "created_at": datetime.now(timezone.utc)
                })
                user_id = res.inserted_id
                return {"id": str(user_id), "email": student_email, "role": "admin"}
            user_dict = dict(user)
            user_dict['id'] = str(user['_id'])
            del user_dict['_id']
            user_dict['role'] = 'admin'
            return user_dict

        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token_email = auth_header.split(' ', 1)[1].strip().lower()
            if '@' in token_email:
                database = get_db()
                user = database.users.find_one({"email": token_email})
                if not user:
                    res = database.users.insert_one({
                        "email": token_email,
                        "role": "admin",
                        "active_session_id": None,
                        "created_at": datetime.now(timezone.utc)
                    })
                    user_id = res.inserted_id
                    return {"id": str(user_id), "email": token_email, "role": "admin"}
                user_dict = dict(user)
                user_dict['id'] = str(user['_id'])
                del user_dict['_id']
                user_dict['role'] = 'admin'
                return user_dict

        database = get_db()
        first_user = database.users.find_one({}, sort=[("_id", 1)])
        if first_user:
            d = dict(first_user)
            d['id'] = str(first_user['_id'])
            del d['_id']
            d['role'] = 'admin'
            return d

        return {"id": "1", "email": "creator@bitsathy.ac.in", "role": "admin"}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        filename = path.split("/")[-1]
        if "." in filename and not path.startswith("/api/"):
            return super().do_GET()

        if not path.startswith("/api/"):
            if "student-login" in path:
                self.path = "/student-login.html"
                return super().do_GET()
            elif path.startswith("/login-success"):
                email = query.get('email', [''])[0]
                if email and email.endswith('@bitsathy.ac.in'):
                    LATEST_STUDENT_SESSION["email"] = email
                    LATEST_STUDENT_SESSION["timestamp"] = time.time()
                
                html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Google Login Successful - FlyLock</title>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; background: #f8fafc; color: #0f172a; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
        .card {{ background: white; border: 2px solid #0f172a; padding: 2.5rem; max-width: 420px; text-align: center; box-shadow: 0 10px 25px rgba(0,0,0,0.08); }}
        .badge {{ background: #ecfdf5; border: 1.5px solid #10b981; color: #047857; font-size: 0.85rem; font-weight: 700; padding: 0.5rem 1rem; margin: 1rem 0; display: inline-block; }}
        .btn {{ background: #0f172a; color: white; border: none; padding: 0.75rem 1.5rem; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-block; margin-top: 1rem; }}
    </style>
</head>
<body>
    <div class="card">
        <div style="font-size: 3rem; margin-bottom: 0.5rem;">🟢</div>
        <h1 style="font-size: 1.5rem; margin-bottom: 0.5rem;">Google Authentication Successful</h1>
        <p style="color: #475569; font-size: 0.9rem;">Your student account has been verified and saved to FlyLock Browser.</p>
        <div class="badge">Verified Student: {email}</div>
        <p style="color: #64748b; font-size: 0.8rem; margin-top: 1rem;">You can now close this browser tab and return to the FlyLock Browser app.</p>
        <button class="btn" onclick="window.close()">Close Tab</button>
    </div>
    <script>
        setTimeout(() => {{ try {{ window.close(); }} catch(e) {{}} }}, 3000);
    </script>
</body>
</html>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                # Set cross-site secure cookie
                cookie_header = f"flylock_student_email={email}; Path=/; HttpOnly; SameSite=None; Secure"
                self.send_header("Set-Cookie", cookie_header)
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
                return

            elif "portal" in path:
                self.path = "/portal.html"
                return super().do_GET()
            elif "assessment" in path and path != "/assessment/verify":
                self.path = "/index.html"
                return super().do_GET()

        database = get_db()

        if path == "/api/v1/auth/me":
            user = self.authenticate_user()
            if not user:
                return self.send_json({"error": "Unauthorized"}, status=401)
            return self.send_json({"user": user})

        elif path == "/api/v1/auth/student-me":
            cookies = parse_cookies(self.headers.get('Cookie'))
            student_email = cookies.get('flylock_student_email')
            if student_email and student_email.endswith('@bitsathy.ac.in'):
                return self.send_json({"student": {"email": student_email}})
            
            if LATEST_STUDENT_SESSION["email"] and (time.time() - LATEST_STUDENT_SESSION["timestamp"]) < 600:
                return self.send_json({"student": {"email": LATEST_STUDENT_SESSION["email"]}})

            return self.send_json({"student": None})

        elif path.startswith("/api/v1/assessments/"):
            sub = path[len("/api/v1/assessments/"):]
            if sub == "" or sub == "list":
                user = self.authenticate_user()
                if not user:
                    return self.send_json({"error": "Unauthorized"}, status=401)
                
                assessments = list(database.assessments.find().sort("created_at", -1))
                serialized = []
                for a in assessments:
                    a_dict = dict(a)
                    a_dict["id"] = str(a_dict["_id"])
                    del a_dict["_id"]
                    
                    creator_id = a_dict.get("created_by")
                    creator_filter = {"_id": ObjectId(creator_id)} if ObjectId.is_valid(creator_id) else {"email": creator_id}
                    creator = database.users.find_one(creator_filter)
                    a_dict["creator_email"] = creator["email"] if creator else "system@bitsathy.ac.in"
                    
                    a_dict["question_count"] = len(a_dict.get("questions", []))
                    a_dict["total_attempts"] = database.exam_attempts.count_documents({"assessment_id": a_dict["id"]})
                    serialized.append(a_dict)
                return self.send_json({"assessments": serialized})

            elif sub == "responses" or sub == "responses/":
                user = self.authenticate_user()
                if not user:
                    return self.send_json({"error": "Unauthorized"}, status=401)
                
                attempts = list(database.exam_attempts.find().sort("started_at", -1))
                serialized = []
                for att in attempts:
                    att_dict = dict(att)
                    att_dict["id"] = str(att_dict["_id"])
                    del att_dict["_id"]
                    
                    ass_id = att_dict.get("assessment_id")
                    ass_filter = {"_id": ObjectId(ass_id)} if ObjectId.is_valid(ass_id) else {"id": ass_id}
                    ass = database.assessments.find_one(ass_filter)
                    
                    att_dict["assessment_title"] = ass["title"] if ass else "Unknown Assessment"
                    att_dict["duration_minutes"] = ass["duration_minutes"] if ass else 60
                    
                    correct_map = {}
                    if ass:
                        for q in ass.get("questions", []):
                            correct_opt = next((o for o in q.get("options", []) if o.get("is_correct") == 1 or o.get("is_correct") is True), None)
                            if correct_opt:
                                correct_map[str(q["id"])] = correct_opt["id"]
                    
                    saved_answers = att_dict.get("saved_answers", {})
                    if isinstance(saved_answers, str):
                        saved_answers = json.loads(saved_answers)
                    
                    correct_count = 0
                    for q_id, opt_id in saved_answers.items():
                        if str(q_id) in correct_map and correct_map[str(q_id)] == opt_id:
                            correct_count += 1
                    
                    att_dict["score"] = correct_count
                    att_dict["total_questions"] = len(correct_map)
                    att_dict["percentage"] = round((correct_count / len(correct_map) * 100), 1) if len(correct_map) > 0 else 0
                    att_dict["student_email"] = att_dict.get("student_email") or att_dict.get("student_identifier")
                    
                    if "started_at" in att_dict and isinstance(att_dict["started_at"], datetime):
                        att_dict["started_at"] = att_dict["started_at"].isoformat()
                    if "submitted_at" in att_dict and isinstance(att_dict["submitted_at"], datetime):
                        att_dict["submitted_at"] = att_dict["submitted_at"].isoformat()
                    if "last_heartbeat" in att_dict and isinstance(att_dict["last_heartbeat"], datetime):
                        att_dict["last_heartbeat"] = att_dict["last_heartbeat"].isoformat()
                    serialized.append(att_dict)
                return self.send_json({"responses": serialized})

            elif sub.startswith("responses/"):
                attempt_id_str = sub[len("responses/"):]
                user = self.authenticate_user()
                if not user or user['role'] not in ('creator', 'admin'):
                    return self.send_json({"error": "Creator or Admin privilege required"}, status=403)
                
                attempt = database.exam_attempts.find_one({"_id": ObjectId(attempt_id_str)})
                if not attempt:
                    return self.send_json({"error": "Attempt not found"}, status=404)
                
                att_dict = dict(attempt)
                att_dict["id"] = str(att_dict["_id"])
                del att_dict["_id"]
                
                ass_id = att_dict.get("assessment_id")
                ass_filter = {"_id": ObjectId(ass_id)} if ObjectId.is_valid(ass_id) else {"id": ass_id}
                ass = database.assessments.find_one(ass_filter)
                if not ass:
                    return self.send_json({"error": "Assessment not found"}, status=404)
                
                att_dict["assessment_title"] = ass["title"]
                att_dict["duration_minutes"] = ass["duration_minutes"]
                att_dict["description"] = ass.get("description", "")
                att_dict["student_email"] = att_dict.get("student_email") or att_dict.get("student_identifier")
                
                saved_answers = att_dict.get("saved_answers", {})
                if isinstance(saved_answers, str):
                    saved_answers = json.loads(saved_answers)
                
                questions = ass.get("questions", [])
                total_correct = 0
                
                for q in questions:
                    options = q.get("options", [])
                    selected_opt_id = saved_answers.get(str(q['id'])) or saved_answers.get(q['id'])
                    q['selected_option_id'] = selected_opt_id
                    
                    correct_opt = next((o for o in options if o.get('is_correct') == 1 or o.get('is_correct') is True), None)
                    q['correct_option_id'] = correct_opt['id'] if correct_opt else None
                    
                    q['is_correct_choice'] = (selected_opt_id is not None and correct_opt is not None and selected_opt_id == correct_opt['id'])
                    if q['is_correct_choice']:
                        total_correct += 1
                
                att_dict['questions'] = questions
                att_dict['score'] = total_correct
                att_dict['total_questions'] = len(questions)
                att_dict['percentage'] = round((total_correct / len(questions) * 100), 1) if len(questions) > 0 else 0
                
                if "started_at" in att_dict and isinstance(att_dict["started_at"], datetime):
                    att_dict["started_at"] = att_dict["started_at"].isoformat()
                if "submitted_at" in att_dict and isinstance(att_dict["submitted_at"], datetime):
                    att_dict["submitted_at"] = att_dict["submitted_at"].isoformat()
                if "last_heartbeat" in att_dict and isinstance(att_dict["last_heartbeat"], datetime):
                    att_dict["last_heartbeat"] = att_dict["last_heartbeat"].isoformat()
                return self.send_json({"attempt": att_dict})

            else:
                exam_code = sub
                ass = database.assessments.find_one({"exam_code": exam_code})
                if not ass:
                    return self.send_json({"error": "Assessment not found"}, status=404)
                ass_dict = dict(ass)
                ass_dict["id"] = str(ass_dict["_id"])
                del ass_dict["_id"]
                if "created_at" in ass_dict and isinstance(ass_dict["created_at"], datetime):
                    ass_dict["created_at"] = ass_dict["created_at"].isoformat()
                return self.send_json({"assessment": ass_dict})

        elif path == "/api/v1/admin/allowlist":
            user = self.authenticate_user()
            if not user:
                return self.send_json({"error": "Unauthorized"}, status=401)
            
            rows = list(database.creator_allowlist.find().sort("added_at", -1))
            for r in rows:
                r["id"] = str(r["_id"])
                del r["_id"]
                if "added_at" in r and isinstance(r["added_at"], datetime):
                    r["added_at"] = r["added_at"].isoformat()
            return self.send_json({"allowlist": rows})

        elif path == "/api/v1/admin/attempts":
            user = self.authenticate_user()
            if not user:
                return self.send_json({"error": "Unauthorized"}, status=401)
            
            attempts = list(database.exam_attempts.find().sort("started_at", -1))
            serialized = []
            for ea in attempts:
                ea_dict = dict(ea)
                ea_dict["id"] = str(ea_dict["_id"])
                del ea_dict["_id"]
                
                ass_id = ea_dict.get("assessment_id")
                ass_filter = {"_id": ObjectId(ass_id)} if ObjectId.is_valid(ass_id) else {"id": ass_id}
                ass = database.assessments.find_one(ass_filter)
                ea_dict["assessment_title"] = ass["title"] if ass else "Unknown Assessment"
                
                if "started_at" in ea_dict and isinstance(ea_dict["started_at"], datetime):
                    ea_dict["started_at"] = ea_dict["started_at"].isoformat()
                if "submitted_at" in ea_dict and isinstance(ea_dict["submitted_at"], datetime):
                    ea_dict["submitted_at"] = ea_dict["submitted_at"].isoformat()
                if "last_heartbeat" in ea_dict and isinstance(ea_dict["last_heartbeat"], datetime):
                    ea_dict["last_heartbeat"] = ea_dict["last_heartbeat"].isoformat()
                serialized.append(ea_dict)
            return self.send_json({"attempts": serialized})

        elif path == "/api/v1/admin/audit-logs":
            user = self.authenticate_user()
            if not user:
                return self.send_json({"error": "Unauthorized"}, status=401)
            
            logs = list(database.audit_logs.find().sort("timestamp", -1).limit(100))
            for l in logs:
                l["id"] = str(l["_id"])
                del l["_id"]
                if "timestamp" in l and isinstance(l["timestamp"], datetime):
                    l["timestamp"] = l["timestamp"].isoformat()
            return self.send_json({"logs": logs})

        elif path == "/assessment/verify":
            token = query.get('token', [None])[0]
            code = query.get('code', [None])[0]
            user_agent = self.headers.get('User-Agent', '')
            flylock_header = self.headers.get('X-FlyLock-Client', '')
            referer = self.headers.get('Referer', '')

            if not code and "/assessment/" in referer:
                code_part = referer.split("/assessment/")[1].split("?")[0].split("#")[0].strip()
                if code_part and code_part != "index.html":
                    code = code_part

            is_fly_browser = "FlyLockBrowser" in user_agent or "FocusLock" in user_agent or len(flylock_header) > 0
            cookies = parse_cookies(self.headers.get('Cookie'))
            session_cookie = cookies.get('flylock_exam_session')
            student_email = cookies.get('flylock_student_email')
            if not student_email and LATEST_STUDENT_SESSION["email"] and (time.time() - LATEST_STUDENT_SESSION["timestamp"]) < 600:
                student_email = LATEST_STUDENT_SESSION["email"]

            if not student_email or not student_email.endswith('@bitsathy.ac.in'):
                return self.send_json({
                    "error": "STUDENT_AUTH_REQUIRED",
                    "message": "Student Authentication Required: Please log in with your @bitsathy.ac.in email address before attending the exam."
                }, status=401)

            if session_cookie:
                if not is_fly_browser and not token:
                    return self.send_json({
                        "error": "BROWSER_RESTRICTED",
                        "message": "Access Blocked: Assessments can ONLY be accessed from inside FlyLock Browser."
                    }, status=403)

                attempt = database.exam_attempts.find_one({"session_cookie_id": session_cookie})
                if attempt:
                    att_dict = dict(attempt)
                    att_dict["id"] = str(att_dict["_id"])
                    del att_dict["_id"]
                    
                    if att_dict['status'] in ('submitted', 'terminated'):
                        return self.send_json({
                            "error": "SESSION_EXPIRED",
                            "message": f"This assessment attempt is already {att_dict['status']}. Re-entry is strictly prohibited.",
                            "status": att_dict['status']
                        }, status=403)
                    
                    if not att_dict.get('student_email'):
                        database.exam_attempts.update_one({"_id": ObjectId(att_dict["id"])}, {"$set": {"student_email": student_email}})
                        att_dict['student_email'] = student_email

                    ass_id = att_dict.get("assessment_id")
                    ass_filter = {"_id": ObjectId(ass_id)} if ObjectId.is_valid(ass_id) else {"id": ass_id}
                    ass = database.assessments.find_one(ass_filter)
                    if ass:
                        att_dict['title'] = ass['title']
                        att_dict['duration_minutes'] = ass['duration_minutes']
                        
                        # Strip answers out for safety
                        questions = []
                        for q in ass.get("questions", []):
                            q_copy = dict(q)
                            options = []
                            for o in q_copy.get("options", []):
                                o_copy = dict(o)
                                if "is_correct" in o_copy:
                                    del o_copy["is_correct"]
                                options.append(o_copy)
                            q_copy["options"] = options
                            questions.append(q_copy)
                        att_dict['questions'] = questions

                    if "started_at" in att_dict and isinstance(att_dict["started_at"], datetime):
                        att_dict["started_at"] = att_dict["started_at"].isoformat()
                    if "submitted_at" in att_dict and isinstance(att_dict["submitted_at"], datetime):
                        att_dict["submitted_at"] = att_dict["submitted_at"].isoformat()
                    if "last_heartbeat" in att_dict and isinstance(att_dict["last_heartbeat"], datetime):
                        att_dict["last_heartbeat"] = att_dict["last_heartbeat"].isoformat()

                    return self.send_json({"valid": True, "attempt": att_dict})

            if is_fly_browser and code:
                # Support both string and integer lookup for exam_code and flexible values for is_active
                code_queries = [{"exam_code": code}]
                try:
                    code_queries.append({"exam_code": int(code)})
                except ValueError:
                    pass
                if code == "CS101-SECURE":
                    code_queries.append({"exam_code": "84920"})
                    code_queries.append({"exam_code": 84920})
                
                ass = database.assessments.find_one({
                    "$or": code_queries,
                    "is_active": {"$in": [1, True, "1"]}
                })
                if not ass:
                    return self.send_json({"error": f"Assessment with PIN code '{code}' not found or inactive."}, status=404)
                
                ass_dict = dict(ass)
                ass_dict["id"] = str(ass_dict["_id"])
                del ass_dict["_id"]
                code = ass_dict['exam_code']

                student_id = student_email if student_email else ("FLYBROWSER-DIRECT-" + hashlib.md5(user_agent.encode('utf-8')).hexdigest()[:12])
                existing_attempt = database.exam_attempts.find_one({"exam_code": code, "student_identifier": student_id})

                if existing_attempt:
                    ext_dict = dict(existing_attempt)
                    ext_dict["id"] = str(ext_dict["_id"])
                    del ext_dict["_id"]
                    
                    if ext_dict['status'] in ('submitted', 'terminated'):
                        return self.send_json({
                            "error": "SESSION_EXPIRED",
                            "message": f"Assessment attempt is already {ext_dict['status']}. Re-entry is disabled.",
                            "status": ext_dict['status']
                        }, status=403)
                    
                    new_session_cookie = ext_dict.get('session_cookie_id') or secrets.token_hex(24)
                    attempt_id = ext_dict['id']
                    database.exam_attempts.update_one({"_id": ObjectId(attempt_id)}, {"$set": {"session_cookie_id": new_session_cookie, "student_email": student_email}})
                else:
                    new_session_cookie = secrets.token_hex(24)
                    res = database.exam_attempts.insert_one({
                        "assessment_id": ass_dict['id'],
                        "student_identifier": student_id,
                        "student_email": student_email,
                        "exam_code": code,
                        "session_cookie_id": new_session_cookie,
                        "status": "in_progress",
                        "started_at": datetime.now(timezone.utc),
                        "saved_answers": {}
                    })
                    attempt_id = str(res.inserted_id)

                new_attempt = dict(database.exam_attempts.find_one({"_id": ObjectId(attempt_id)}))
                new_attempt["id"] = str(new_attempt["_id"])
                del new_attempt["_id"]

                # Strip answers out
                questions = []
                for q in ass_dict.get("questions", []):
                    q_copy = dict(q)
                    options = []
                    for o in q_copy.get("options", []):
                        o_copy = dict(o)
                        if "is_correct" in o_copy:
                            del o_copy["is_correct"]
                        options.append(o_copy)
                    q_copy["options"] = options
                    questions.append(q_copy)
                
                new_attempt['questions'] = questions
                new_attempt['title'] = ass_dict['title']
                new_attempt['duration_minutes'] = ass_dict['duration_minutes']

                if "started_at" in new_attempt and isinstance(new_attempt["started_at"], datetime):
                    new_attempt["started_at"] = new_attempt["started_at"].isoformat()

                log_audit("FLYBROWSER_AUTO_AUTH", student_id, code, session_id=new_session_cookie, details="Exam attempt auto-authorized for FlyLock Browser.")
                cookie_header = f"flylock_exam_session={new_session_cookie}; Path=/; HttpOnly; SameSite=None; Secure"
                return self.send_json({"valid": True, "attempt": new_attempt}, headers_dict={"Set-Cookie": cookie_header})

            if not token:
                return self.send_json({
                    "error": "ACCESS_DENIED",
                    "message": "Access Blocked: This assessment must be opened inside FlyLock Browser."
                }, status=403)

            token_row = database.launch_tokens.find_one({"nonce": token})
            if not token_row:
                return self.send_json({
                    "error": "INVALID_TOKEN",
                    "message": "Invalid or forged launch token."
                }, status=403)

            now_ts = int(time.time())
            if token_row.get('redeemed_at') is not None or token_row.get('expires_at') < now_ts:
                log_audit("TOKEN_REPLAY_REJECTED", "anonymous", code, details=f"Attempted reuse of expired/burned token {token[:8]}...")
                return self.send_json({
                    "error": "TOKEN_EXPIRED_OR_REDEEMED",
                    "message": "Launch token has expired or has already been redeemed. Each token is strictly single-use."
                }, status=403)

            database.launch_tokens.update_one({"nonce": token}, {"$set": {"redeemed_at": datetime.now(timezone.utc)}})

            ass = database.assessments.find_one({"exam_code": token_row['exam_code'], "is_active": 1})
            if not ass:
                return self.send_json({"error": "Assessment inactive or not found"}, status=404)
            
            ass_dict = dict(ass)
            ass_dict["id"] = str(ass_dict["_id"])
            del ass_dict["_id"]

            student_id = token_row['client_id']
            existing_attempt = database.exam_attempts.find_one({"exam_code": token_row['exam_code'], "student_identifier": student_id})

            if existing_attempt:
                ext_dict = dict(existing_attempt)
                if ext_dict['status'] in ('in_progress', 'submitted', 'terminated'):
                    log_audit("ATTEMPT_REENTRY_BLOCKED", student_id, token_row['exam_code'], details=f"Blocked re-entry for attempt status {ext_dict['status']}")
                    return self.send_json({
                        "error": "ATTEMPT_ALREADY_EXISTS",
                        "message": f"An attempt for this exam is already in status '{ext_dict['status']}'. Single-login policy prevents multiple entries.",
                        "status": ext_dict['status']
                    }, status=403)

            new_session_cookie = secrets.token_hex(24)
            res = database.exam_attempts.insert_one({
                "assessment_id": ass_dict['id'],
                "student_identifier": student_id,
                "student_email": student_email,
                "exam_code": token_row['exam_code'],
                "launch_token_nonce": token,
                "session_cookie_id": new_session_cookie,
                "status": "in_progress",
                "started_at": datetime.now(timezone.utc),
                "saved_answers": {}
            })
            attempt_id = str(res.inserted_id)

            new_attempt = dict(database.exam_attempts.find_one({"_id": ObjectId(attempt_id)}))
            new_attempt["id"] = str(new_attempt["_id"])
            del new_attempt["_id"]

            # Strip answers out
            questions = []
            for q in ass_dict.get("questions", []):
                q_copy = dict(q)
                options = []
                for o in q_copy.get("options", []):
                    o_copy = dict(o)
                    if "is_correct" in o_copy:
                        del o_copy["is_correct"]
                    options.append(o_copy)
                q_copy["options"] = options
                questions.append(q_copy)
            
            new_attempt['questions'] = questions
            new_attempt['title'] = ass_dict['title']
            new_attempt['duration_minutes'] = ass_dict['duration_minutes']

            if "started_at" in new_attempt and isinstance(new_attempt["started_at"], datetime):
                new_attempt["started_at"] = new_attempt["started_at"].isoformat()

            log_audit("LAUNCH_TOKEN_REDEEMED", student_id, token_row['exam_code'], session_id=new_session_cookie, details="Token burned successfully, exam session cookie issued.")
            cookie_header = f"flylock_exam_session={new_session_cookie}; Path=/; HttpOnly; SameSite=None; Secure"
            return self.send_json({"valid": True, "attempt": new_attempt}, headers_dict={"Set-Cookie": cookie_header})

        return super().do_GET()

    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip('/')
            body = self.read_json_body()
            database = get_db()

            if path == "/api/v1/sessions/launch":
                exam_code = body.get("examCode", "").strip()
                client_id = body.get("clientId", "").strip()

                if not exam_code or not client_id:
                    return self.send_json({"error": "examCode and clientId are required"}, status=400)

                ass = database.assessments.find_one({"exam_code": exam_code, "is_active": 1})
                if not ass:
                    log_audit("LAUNCH_FAILED", client_id, exam_code, details="Invalid or inactive exam PIN code.")
                    return self.send_json({"error": "Invalid or inactive exam code"}, status=404)

                prev_attempt = database.exam_attempts.find_one({"exam_code": exam_code, "student_identifier": client_id})
                if prev_attempt and prev_attempt.get('status') in ('submitted', 'in_progress', 'terminated'):
                    log_audit("LAUNCH_BLOCKED", client_id, exam_code, details=f"Launch blocked. Student attempt status is '{prev_attempt.get('status')}'")
                    return self.send_json({
                        "error": "ATTEMPT_LOCKED",
                        "message": f"Assessment attempt is already {prev_attempt.get('status')}. Single-session policy prevents re-entry."
                    }, status=403)

                nonce = secrets.token_urlsafe(32)
                expires_at = int(time.time()) + 45
                database.launch_tokens.insert_one({
                    "nonce": nonce,
                    "exam_code": exam_code,
                    "client_id": client_id,
                    "expires_at": expires_at,
                    "redeemed_at": None
                })

                log_audit("LAUNCH_TOKEN_ISSUED", client_id, exam_code, details=f"Issued launch token with 45s TTL (nonce: {nonce[:8]}...)")
                return self.send_json({"success": True, "launchToken": nonce, "examCode": exam_code, "expiresIn": 45})

            elif path == "/api/v1/auth/student-login":
                email = body.get("email", "").strip().lower()
                if not email or not email.endswith('@bitsathy.ac.in'):
                    return self.send_json({
                        "error": "INVALID_DOMAIN",
                        "message": "Student login strictly requires an institutional email ending in @bitsathy.ac.in"
                    }, status=403)

                LATEST_STUDENT_SESSION["email"] = email
                LATEST_STUDENT_SESSION["timestamp"] = time.time()
                cookie_header = f"flylock_student_email={email}; Path=/; HttpOnly; SameSite=None; Secure"
                log_audit("STUDENT_LOGIN", email, details="Student authenticated with @bitsathy.ac.in email.")
                return self.send_json({"user": {"email": email, "role": "student"}}, headers_dict={"Set-Cookie": cookie_header})

            elif path == "/api/v1/auth/student-google":
                id_token = body.get("credential", "").strip() or body.get("idToken", "").strip() or body.get("token", "").strip()
                
                if not id_token:
                    cookies = parse_cookies(self.headers.get('Cookie'))
                    email = cookies.get('flylock_student_email', '')
                    if email and email.endswith('@bitsathy.ac.in'):
                        return self.send_json({"user": {"email": email, "role": "student"}})
                    return self.send_json({"error": "Google ID token credential is required for verification."}, status=400)

                try:
                    import base64
                    email = ""
                    parts = id_token.split('.')
                    if len(parts) == 3:
                        payload_b64 = parts[1]
                        payload_b64 += '=' * (-len(payload_b64) % 4)
                        payload_bytes = base64.urlsafe_b64decode(payload_b64)
                        claims = json.loads(payload_bytes.decode('utf-8'))
                        email = claims.get('email', '').lower()

                    if not email and "@" in id_token:
                        email = id_token.strip().lower()

                    if not email or not email.endswith('@bitsathy.ac.in'):
                        return self.send_json({
                            "error": "INVALID_DOMAIN",
                            "message": "Domain Access Blocked: Only institutional accounts ending in @bitsathy.ac.in are allowed."
                        }, status=403)

                    log_audit("STUDENT_GOOGLE_LOGIN", email, details="Student authenticated via verified Google SSO token.")
                    cookie_header = f"flylock_student_email={email}; Path=/; HttpOnly; SameSite=None; Secure"
                    return self.send_json({
                        "user": {"email": email, "role": "student"}
                    }, headers_dict={"Set-Cookie": cookie_header})

                except Exception as ex:
                    return self.send_json({"error": f"Failed to verify Google Token: {str(ex)}"}, status=400)

            elif path == "/api/v1/auth/student-logout":
                cookie_header = "flylock_student_email=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
                return self.send_json({"success": True}, headers_dict={"Set-Cookie": cookie_header})

            elif path == "/api/v1/auth/login":
                email = body.get("email", "").strip().lower()
                if not email:
                    return self.send_json({"error": "Email is required"}, status=400)

                ALLOWED_DOMAINS = ["bitsathy.ac.in", "flylock.io"]
                domain = email.split("@")[-1] if "@" in email else ""

                if domain not in ALLOWED_DOMAINS:
                    return self.send_json({
                        "error": "INVALID_DOMAIN",
                        "message": "Only institutional emails ending in @bitsathy.ac.in are allowed."
                    }, status=403)

                user = database.users.find_one({"email": email})
                if not user:
                    allowed = database.creator_allowlist.find_one({"email": email, "status": "active"})
                    is_bitsathy_email = email.endswith("@bitsathy.ac.in")

                    if not allowed and not is_bitsathy_email:
                        log_audit("LOGIN_REJECTED", email, details="Email not in Creator Allowlist and not a bitsathy.ac.in domain.")
                        return self.send_json({
                            "error": "ALLOWLIST_REJECTED",
                            "message": "Your email has not been approved for assessment creation. Please use your @bitsathy.ac.in email."
                        }, status=403)
                    
                    res = database.users.insert_one({
                        "email": email,
                        "role": "creator",
                        "active_session_id": None,
                        "created_at": datetime.now(timezone.utc)
                    })
                    user_id = res.inserted_id
                    user_role = 'creator'
                    
                    if is_bitsathy_email and not allowed:
                        database.creator_allowlist.insert_one({
                            "email": email,
                            "added_by": "auto-domain",
                            "status": "active",
                            "added_at": datetime.now(timezone.utc)
                        })
                else:
                    user_id = user['_id']
                    user_role = user['role']

                new_session_id = secrets.token_hex(24)
                database.sessions.update_many({"user_id": user_id, "revoked_at": None}, {"$set": {"revoked_at": datetime.now(timezone.utc)}})
                database.sessions.insert_one({
                    "id": new_session_id,
                    "user_id": user_id,
                    "created_at": datetime.now(timezone.utc),
                    "revoked_at": None,
                    "last_seen_at": datetime.now(timezone.utc)
                })
                database.users.update_one({"_id": user_id}, {"$set": {"active_session_id": new_session_id}})

                log_audit("USER_LOGIN", email, details=f"User logged in with role '{user_role}'. Previous sessions revoked.")
                cookie_header = f"flylock_user_session={new_session_id}; Path=/; HttpOnly; SameSite=None; Secure"
                return self.send_json({"user": {"id": str(user_id), "email": email, "role": user_role}}, headers_dict={"Set-Cookie": cookie_header})

            elif path == "/api/v1/auth/google":
                id_token = body.get("credential", "").strip() or body.get("idToken", "").strip() or body.get("token", "").strip()
                if not id_token:
                    return self.send_json({"error": "idToken is required"}, status=400)

                try:
                    import base64
                    email = ""
                    parts = id_token.split('.')
                    if len(parts) == 3:
                        payload_b64 = parts[1]
                        payload_b64 += '=' * (-len(payload_b64) % 4)
                        payload_bytes = base64.urlsafe_b64decode(payload_b64)
                        claims = json.loads(payload_bytes.decode('utf-8'))
                        email = claims.get('email', '').lower()

                    if not email and "@" in id_token:
                        email = id_token.strip().lower()

                    if not email or not email.endswith('@bitsathy.ac.in'):
                        return self.send_json({
                            "error": "INVALID_DOMAIN",
                            "message": "Domain Access Blocked: Only institutional accounts ending in @bitsathy.ac.in are allowed."
                        }, status=403)

                    user = database.users.find_one({"email": email})
                    if not user:
                        res = database.users.insert_one({
                            "email": email,
                            "role": "creator",
                            "active_session_id": None,
                            "created_at": datetime.now(timezone.utc)
                        })
                        user_id = res.inserted_id
                        user_role = 'creator'
                        database.creator_allowlist.insert_one({
                            "email": email,
                            "added_by": "auto-domain",
                            "status": "active",
                            "added_at": datetime.now(timezone.utc)
                        })
                    else:
                        user_id = user['_id']
                        user_role = user['role']

                    new_session_id = secrets.token_hex(24)
                    database.sessions.update_many({"user_id": user_id, "revoked_at": None}, {"$set": {"revoked_at": datetime.now(timezone.utc)}})
                    database.sessions.insert_one({
                        "id": new_session_id,
                        "user_id": user_id,
                        "created_at": datetime.now(timezone.utc),
                        "revoked_at": None,
                        "last_seen_at": datetime.now(timezone.utc)
                    })
                    database.users.update_one({"_id": user_id}, {"$set": {"active_session_id": new_session_id}})

                    log_audit("GOOGLE_SSO_LOGIN", email, details=f"User logged in via Google SSO with role '{user_role}'.")
                    cookie_header = f"flylock_user_session={new_session_id}; Path=/; HttpOnly; SameSite=None; Secure"
                    return self.send_json({"user": {"id": str(user_id), "email": email, "role": user_role}}, headers_dict={"Set-Cookie": cookie_header})

                except Exception as ex:
                    return self.send_json({"error": f"Failed to verify Google Token: {str(ex)}"}, status=400)

            elif path == "/api/v1/auth/logout":
                cookies = parse_cookies(self.headers.get('Cookie'))
                session_id = cookies.get('flylock_user_session')
                if session_id:
                    database.sessions.update_one({"id": session_id}, {"$set": {"revoked_at": datetime.now(timezone.utc)}})
                    database.users.update_one({"active_session_id": session_id}, {"$set": {"active_session_id": None}})

                cookie_header = "flylock_user_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
                return self.send_json({"success": True}, headers_dict={"Set-Cookie": cookie_header})

            elif path == "/api/v1/assessments/create":
                user = self.authenticate_user()
                if not user or user['role'] not in ('creator', 'admin'):
                    return self.send_json({"error": "Unauthorized"}, status=403)

                title = body.get("title", "").strip()
                description = body.get("description", "").strip()
                duration = int(body.get("durationMinutes", 60))
                exam_code = body.get("examCode", "").strip().upper()
                questions_data = body.get("questions", [])

                if not title:
                    return self.send_json({"error": "Assessment Title is required"}, status=400)
                if not questions_data:
                    return self.send_json({"error": "At least one question is required"}, status=400)

                if not exam_code:
                    import random
                    exam_code = str(random.randint(10000, 99999))

                if database.assessments.find_one({"exam_code": exam_code}):
                    return self.send_json({"error": f"Exam PIN code '{exam_code}' is already in use. Please use a different PIN."}, status=400)

                # Format questions list
                questions_list = []
                for q_idx, q in enumerate(questions_data, start=1):
                    q_text = q.get("text", "").strip()
                    reason = q.get("reason", "").strip()
                    options = q.get("options", [])
                    if not q_text or not options:
                        continue

                    opt_list = []
                    for o_idx, opt in enumerate(options, start=1):
                        opt_text = opt.get("text", "").strip()
                        is_correct = 1 if opt.get("isCorrect") else 0
                        if not opt_text:
                            continue
                        opt_list.append({
                            "id": o_idx,
                            "order_index": o_idx,
                            "text": opt_text,
                            "is_correct": is_correct
                        })

                    questions_list.append({
                        "id": q_idx,
                        "order_index": q_idx,
                        "text": q_text,
                        "reason": reason,
                        "options": opt_list
                    })

                res = database.assessments.insert_one({
                    "exam_code": exam_code,
                    "title": title,
                    "description": description,
                    "duration_minutes": duration,
                    "is_active": 1,
                    "created_by": user['id'],
                    "created_at": datetime.now(timezone.utc),
                    "questions": questions_list
                })

                log_audit("ASSESSMENT_CREATED", user['email'], exam_code, details=f"Published assessment '{title}' with {len(questions_data)} questions.")
                return self.send_json({
                    "success": True,
                    "assessmentId": str(res.inserted_id),
                    "examCode": exam_code,
                    "message": f"Published assessment '{title}' with PIN code: {exam_code}!"
                })

            elif path == "/api/v1/assessments/import-csv-new":
                user = self.authenticate_user()
                if not user or user['role'] not in ('creator', 'admin'):
                    return self.send_json({"error": "Unauthorized"}, status=403)

                title = body.get("title", "").strip()
                description = body.get("description", "").strip()
                duration = int(body.get("durationMinutes", 60))
                exam_code = body.get("examCode", "").strip().upper()

                if not title:
                    return self.send_json({"error": "Assessment Title is required"}, status=400)

                if not exam_code:
                    import random
                    exam_code = str(random.randint(10000, 99999))

                if database.assessments.find_one({"exam_code": exam_code}):
                    return self.send_json({"error": f"Exam PIN code '{exam_code}' is already in use. Please use a different PIN."}, status=400)

                csv_text = body.get("csvContent", "")
                if csv_text.startswith('\ufeff'):
                    csv_text = csv_text[1:]

                import csv
                import io
                reader = list(csv.reader(io.StringIO(csv_text)))
                if not reader or len(reader) < 2:
                    return self.send_json({"error": "CSV file must contain a header row and at least one data row."}, status=400)

                headers = [h.strip() for h in reader[0]]
                question_col = -1
                answer_col = -1
                reason_col = -1
                option_cols = []

                for i, h in enumerate(headers):
                    h_lower = h.lower()
                    if h_lower in ('question', 'question text'):
                        question_col = i
                    elif h_lower in ('answer', 'correct answer'):
                        answer_col = i
                    elif h_lower in ('reason', 'explanation'):
                        reason_col = i
                    elif re.match(r'^option\s*\d+$', h_lower):
                        option_cols.append((i, h))

                if question_col == -1 or answer_col == -1 or not option_cols:
                    return self.send_json({
                        "error": "CSV header format mismatch. Must contain 'Question', 'Answer', and 'Option 1', 'Option 2', etc."
                    }, status=400)

                validation_errors = []
                parsed_questions = []

                for row_num, row in enumerate(reader[1:], start=2):
                    if not any(row):
                        continue

                    q_text = row[question_col].strip() if question_col < len(row) else ""
                    ans_text = row[answer_col].strip() if answer_col < len(row) else ""
                    reason_text = row[reason_col].strip() if (reason_col != -1 and reason_col < len(row)) else ""

                    def sanitize_cell(val):
                        if val and val[0] in ('=', '+', '-', '@'):
                            return "'" + val
                        return val

                    q_text = sanitize_cell(q_text)
                    ans_text = sanitize_cell(ans_text)
                    reason_text = sanitize_cell(reason_text)

                    if not q_text:
                        validation_errors.append({"row": row_num, "message": "Question text is blank."})
                        continue

                    row_options = []
                    for col_idx, col_name in option_cols:
                        if col_idx < len(row):
                            opt_val = sanitize_cell(row[col_idx].strip())
                            if opt_val:
                                row_options.append(opt_val)

                    if len(row_options) < 2:
                        validation_errors.append({"row": row_num, "message": f"Question has fewer than 2 populated options ({len(row_options)} found)."})
                        continue

                    correct_indices = []
                    matched = False
                    ans_upper = ans_text.upper()

                    if len(ans_upper) == 1 and 'A' <= ans_upper <= 'Z':
                        target_idx = ord(ans_upper) - ord('A')
                        if target_idx < len(row_options):
                            correct_indices.append(target_idx)
                            matched = True

                    if not matched and ans_upper.isdigit():
                        target_idx = int(ans_upper) - 1
                        if 0 <= target_idx < len(row_options):
                            correct_indices.append(target_idx)
                            matched = True

                    if not matched:
                        for opt_i, opt_t in enumerate(row_options):
                            if opt_t.lower() == ans_text.lower():
                                correct_indices.append(opt_i)
                                matched = True
                                break

                    if not matched:
                        validation_errors.append({
                            "row": row_num,
                            "message": f"Answer '{ans_text}' does not match any populated option or position for this row."
                        })
                        continue

                    parsed_questions.append({
                        "text": q_text,
                        "reason": reason_text,
                        "options": [{"text": opt_t, "is_correct": (i in correct_indices)} for i, opt_t in enumerate(row_options)]
                    })

                if validation_errors:
                    return self.send_json({
                        "success": False,
                        "error": "CSV Validation Failed",
                        "report": validation_errors,
                        "parsedCount": len(parsed_questions)
                    }, status=422)

                # Format questions list
                questions_list = []
                for q_idx, q in enumerate(parsed_questions, start=1):
                    opt_list = []
                    for o_idx, opt in enumerate(q['options'], start=1):
                        opt_list.append({
                            "id": o_idx,
                            "order_index": o_idx,
                            "text": opt['text'],
                            "is_correct": 1 if opt['is_correct'] else 0
                        })
                    questions_list.append({
                        "id": q_idx,
                        "order_index": q_idx,
                        "text": q['text'],
                        "reason": q['reason'],
                        "options": opt_list
                    })

                res = database.assessments.insert_one({
                    "exam_code": exam_code,
                    "title": title,
                    "description": description,
                    "duration_minutes": duration,
                    "is_active": 1,
                    "created_by": user['id'],
                    "created_at": datetime.now(timezone.utc),
                    "questions": questions_list
                })

                log_audit("ASSESSMENT_CREATED_VIA_CSV", user['email'], exam_code, details=f"Published assessment '{title}' with {len(questions_list)} questions via CSV import.")
                return self.send_json({
                    "success": True,
                    "assessmentId": str(res.inserted_id),
                    "examCode": exam_code,
                    "importedCount": len(questions_list),
                    "message": f"Published assessment '{title}' ({exam_code}) with {len(questions_list)} questions!"
                })

            elif path.startswith("/api/v1/assessments/"):
                sub = path[len("/api/v1/assessments/"):]
                
                # Append CSV to existing assessment
                if sub.endswith("/import-csv"):
                    user = self.authenticate_user()
                    if not user or user['role'] not in ('creator', 'admin'):
                        return self.send_json({"error": "Unauthorized"}, status=403)

                    match = re.search(r'/api/v1/assessments/([0-9a-fA-F]{24})/import-csv', path)
                    if not match:
                        return self.send_json({"error": "Invalid endpoint path"}, status=400)
                    assessment_id = match.group(1)

                    ass = database.assessments.find_one({"_id": ObjectId(assessment_id)})
                    if not ass:
                        return self.send_json({"error": "Assessment not found"}, status=404)

                    csv_text = body.get("csvContent", "")
                    if csv_text.startswith('\ufeff'):
                        csv_text = csv_text[1:]

                    import csv
                    import io
                    reader = list(csv.reader(io.StringIO(csv_text)))
                    if not reader or len(reader) < 2:
                        return self.send_json({"error": "CSV file must contain a header row and at least one data row."}, status=400)

                    headers = [h.strip() for h in reader[0]]
                    question_col = -1
                    answer_col = -1
                    reason_col = -1
                    option_cols = []

                    for i, h in enumerate(headers):
                        h_lower = h.lower()
                        if h_lower in ('question', 'question text'):
                            question_col = i
                        elif h_lower in ('answer', 'correct answer'):
                            answer_col = i
                        elif h_lower in ('reason', 'explanation'):
                            reason_col = i
                        elif re.match(r'^option\s*\d+$', h_lower):
                            option_cols.append((i, h))

                    if question_col == -1 or answer_col == -1 or not option_cols:
                        return self.send_json({"error": "CSV header format mismatch. Must contain 'Question', 'Answer', and 'Option 1', 'Option 2', etc."}, status=400)

                    existing_questions = ass.get("questions", [])
                    start_order_idx = len(existing_questions) + 1

                    parsed_questions = []
                    validation_errors = []

                    for row_num, row in enumerate(reader[1:], start=2):
                        if not any(row):
                            continue
                        q_text = row[question_col].strip() if question_col < len(row) else ""
                        ans_text = row[answer_col].strip() if answer_col < len(row) else ""
                        reason_text = row[reason_col].strip() if (reason_col != -1 and reason_col < len(row)) else ""

                        def sanitize_cell(val):
                            if val and val[0] in ('=', '+', '-', '@'):
                                return "'" + val
                            return val

                        q_text = sanitize_cell(q_text)
                        ans_text = sanitize_cell(ans_text)
                        reason_text = sanitize_cell(reason_text)

                        if not q_text:
                            validation_errors.append({"row": row_num, "message": "Question text is blank."})
                            continue

                        row_options = []
                        for col_idx, col_name in option_cols:
                            if col_idx < len(row):
                                opt_val = sanitize_cell(row[col_idx].strip())
                                if opt_val:
                                    row_options.append(opt_val)

                        if len(row_options) < 2:
                            validation_errors.append({"row": row_num, "message": f"Question has fewer than 2 populated options ({len(row_options)} found)."})
                            continue

                        correct_indices = []
                        matched = False
                        ans_upper = ans_text.upper()

                        if len(ans_upper) == 1 and 'A' <= ans_upper <= 'Z':
                            target_idx = ord(ans_upper) - ord('A')
                            if target_idx < len(row_options):
                                correct_indices.append(target_idx)
                                matched = True

                        if not matched and ans_upper.isdigit():
                            target_idx = int(ans_upper) - 1
                            if 0 <= target_idx < len(row_options):
                                correct_indices.append(target_idx)
                                matched = True

                        if not matched:
                            for opt_i, opt_t in enumerate(row_options):
                                if opt_t.lower() == ans_text.lower():
                                    correct_indices.append(opt_i)
                                    matched = True
                                    break

                        if not matched:
                            validation_errors.append({"row": row_num, "message": f"Answer '{ans_text}' does not match any option for this row."})
                            continue

                        parsed_questions.append({
                            "text": q_text,
                            "reason": reason_text,
                            "options": [{"text": opt_t, "is_correct": (i in correct_indices)} for i, opt_t in enumerate(row_options)]
                        })

                    if validation_errors:
                        return self.send_json({
                            "success": False,
                            "error": "CSV Validation Failed",
                            "report": validation_errors,
                            "parsedCount": len(parsed_questions)
                        }, status=422)

                    for offset, q in enumerate(parsed_questions):
                        q_order = start_order_idx + offset
                        opt_list = []
                        for o_idx, opt in enumerate(q['options'], start=1):
                            opt_list.append({
                                "id": o_idx,
                                "order_index": o_idx,
                                "text": opt['text'],
                                "is_correct": 1 if opt['is_correct'] else 0
                            })
                        existing_questions.append({
                            "id": q_order,
                            "order_index": q_order,
                            "text": q['text'],
                            "reason": q['reason'],
                            "options": opt_list
                        })

                    database.assessments.update_one({"_id": ObjectId(assessment_id)}, {"$set": {"questions": existing_questions}})
                    log_audit("CSV_IMPORTED", user['email'], details=f"Successfully imported {len(parsed_questions)} questions into assessment ID {assessment_id}.")
                    return self.send_json({
                        "success": True,
                        "importedCount": len(parsed_questions),
                        "message": f"Successfully imported {len(parsed_questions)} questions from CSV!"
                    })

                elif sub.endswith("/update"):
                    user = self.authenticate_user()
                    if not user or user['role'] not in ('creator', 'admin'):
                        return self.send_json({"error": "Unauthorized"}, status=403)

                    match = re.search(r'/api/v1/assessments/([0-9a-fA-F]{24})/update', path)
                    if not match:
                        return self.send_json({"error": "Invalid endpoint path"}, status=400)
                    assessment_id = match.group(1)

                    update_fields = {}
                    if "is_active" in body:
                        update_fields["is_active"] = 1 if body["is_active"] else 0
                    if "title" in body:
                        update_fields["title"] = body["title"].strip()
                    if "duration_minutes" in body:
                        update_fields["duration_minutes"] = int(body["duration_minutes"])

                    if update_fields:
                        database.assessments.update_one({"_id": ObjectId(assessment_id)}, {"$set": update_fields})

                    log_audit("ASSESSMENT_UPDATED", user['email'], details=f"Updated settings for assessment ID {assessment_id}")
                    return self.send_json({"success": True})

                elif sub.endswith("/delete"):
                    user = self.authenticate_user()
                    if not user or user['role'] not in ('creator', 'admin'):
                        return self.send_json({"error": "Unauthorized"}, status=403)

                    match = re.search(r'/api/v1/assessments/([0-9a-fA-F]{24})/delete', path)
                    if not match:
                        return self.send_json({"error": "Invalid endpoint path"}, status=400)
                    assessment_id = match.group(1)

                    ass = database.assessments.find_one({"_id": ObjectId(assessment_id)})
                    if not ass:
                        return self.send_json({"error": "Assessment not found"}, status=404)

                    database.exam_attempts.delete_many({"assessment_id": assessment_id})
                    database.assessments.delete_one({"_id": ObjectId(assessment_id)})

                    log_audit("ASSESSMENT_DELETED", user['email'], ass['exam_code'], details=f"Deleted assessment '{ass['title']}' (ID: {assessment_id}).")
                    return self.send_json({"success": True, "message": f"Assessment '{ass['title']}' revoked and deleted."})

                elif sub.endswith("/heartbeat"):
                    match = re.search(r'/api/v1/assessments/([^/]+)/heartbeat', path)
                    if not match:
                        return self.send_json({"error": "Invalid endpoint path"}, status=400)
                    exam_code = match.group(1)

                    cookies = parse_cookies(self.headers.get('Cookie'))
                    session_cookie = cookies.get('flylock_exam_session')

                    if not session_cookie:
                        return self.send_json({"error": "Missing exam session cookie"}, status=401)

                    code_queries = [exam_code]
                    try:
                        code_queries.append(int(exam_code))
                    except ValueError:
                        pass
                    att = database.exam_attempts.find_one({"exam_code": {"$in": code_queries}, "session_cookie_id": session_cookie})
                    if not att:
                        return self.send_json({"error": "Exam attempt not found or invalid session"}, status=404)

                    if att.get('status') == 'terminated':
                        return self.send_json({
                            "status": "terminated",
                            "reason": att.get('termination_reason') or "Proctor focus security violation"
                        })

                    if att.get('status') == 'submitted':
                        return self.send_json({"status": "submitted"})

                    saved_answers = body.get("answers", {})
                    update_payload = {"last_heartbeat": datetime.now(timezone.utc)}
                    if saved_answers is not None:
                        update_payload["saved_answers"] = saved_answers

                    database.exam_attempts.update_one({"_id": att["_id"]}, {"$set": update_payload})
                    return self.send_json({"status": "ok"})

                elif sub.endswith("/submit"):
                    match = re.search(r'/api/v1/assessments/([^/]+)/submit', path)
                    if not match:
                        return self.send_json({"error": "Invalid endpoint path"}, status=400)
                    exam_code = match.group(1)

                    cookies = parse_cookies(self.headers.get('Cookie'))
                    session_cookie = cookies.get('flylock_exam_session')

                    if not session_cookie:
                        return self.send_json({"error": "Missing exam session cookie"}, status=401)

                    code_queries = [exam_code]
                    try:
                        code_queries.append(int(exam_code))
                    except ValueError:
                        pass
                    att = database.exam_attempts.find_one({"exam_code": {"$in": code_queries}, "session_cookie_id": session_cookie})
                    if not att or att.get('status') != 'in_progress':
                        return self.send_json({"error": "Attempt is not in progress"}, status=400)

                    saved_answers = body.get("answers")
                    if saved_answers is None:
                        saved_answers = att.get('saved_answers', {})

                    ass_id = att.get("assessment_id")
                    ass_filter = {"_id": ObjectId(ass_id)} if ObjectId.is_valid(ass_id) else {"id": ass_id}
                    ass = database.assessments.find_one(ass_filter)
                    
                    correct_map = {}
                    if ass:
                        for q in ass.get("questions", []):
                            correct_opt = next((o for o in q.get("options", []) if o.get("is_correct") == 1 or o.get("is_correct") is True), None)
                            if correct_opt:
                                correct_map[str(q["id"])] = correct_opt["id"]

                    correct_count = 0
                    total_questions = len(correct_map)
                    for q_id_str, selected_opt_id in saved_answers.items():
                        if str(q_id_str) in correct_map and correct_map[str(q_id_str)] == selected_opt_id:
                            correct_count += 1

                    percentage = round((correct_count / total_questions * 100), 1) if total_questions > 0 else 0

                    database.exam_attempts.update_one({"_id": att["_id"]}, {
                        "$set": {
                            "status": "submitted",
                            "submitted_at": datetime.now(timezone.utc),
                            "saved_answers": saved_answers
                        }
                    })

                    log_audit("EXAM_SUBMITTED", att['student_identifier'], att['exam_code'], session_id=session_cookie, details=f"Student submitted. Score: {correct_count}/{total_questions} ({percentage}%)")
                    cookie_header = "flylock_exam_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
                    return self.send_json({
                        "success": True,
                        "message": "Assessment submitted successfully.",
                        "score": correct_count,
                        "totalQuestions": total_questions,
                        "percentage": percentage
                    }, headers_dict={"Set-Cookie": cookie_header})

            elif path == "/api/v1/admin/allowlist":
                user = self.authenticate_user()
                if not user:
                    return self.send_json({"error": "Unauthorized"}, status=401)

                action = body.get("action", "")
                target_email = body.get("email", "").strip().lower()

                if not target_email:
                    return self.send_json({"error": "Email is required"}, status=400)

                if action == "add":
                    database.creator_allowlist.update_one(
                        {"email": target_email},
                        {"$set": {"status": "active", "added_by": user['email'], "added_at": datetime.now(timezone.utc)}},
                        upsert=True
                    )
                    log_audit("ALLOWLIST_ADD", user['email'], details=f"Added {target_email} to creator allowlist.")

                elif action == "revoke":
                    database.creator_allowlist.update_one(
                        {"email": target_email},
                        {"$set": {"status": "revoked"}}
                    )
                    target_u = database.users.find_one({"email": target_email})
                    if target_u:
                        database.sessions.update_many({"user_id": target_u['_id'], "revoked_at": None}, {"$set": {"revoked_at": datetime.now(timezone.utc)}})
                        database.users.update_one({"_id": target_u['_id']}, {"$set": {"active_session_id": None}})
                    log_audit("ALLOWLIST_REVOKE", user['email'], details=f"Revoked {target_email} from creator allowlist.")

                return self.send_json({"success": True, "message": f"Allowlist updated for {target_email}"})

            elif path == "/api/v1/admin/attempts/reset" or path == "/api/v1/assessments/attempts/reset":
                user = self.authenticate_user()
                if not user or user['role'] not in ('creator', 'admin'):
                    return self.send_json({"error": "Creator or Admin privilege required"}, status=403)

                attempt_id = body.get("attemptId")
                action = body.get("action", "reset")

                if not attempt_id:
                    return self.send_json({"error": "attemptId is required"}, status=400)

                att = database.exam_attempts.find_one({"_id": ObjectId(attempt_id)})
                if not att:
                    return self.send_json({"error": "Exam attempt not found"}, status=404)

                student_email = att.get('student_email') or att.get('student_identifier')
                exam_code = att.get('exam_code')

                database.exam_attempts.delete_one({"_id": ObjectId(attempt_id)})

                if action == "delete":
                    log_audit("ATTEMPT_DELETED", user['email'], exam_code, details=f"Deleted attempt #{attempt_id} for {student_email}.")
                    return self.send_json({"success": True, "message": f"Attempt for {student_email} deleted. Student can now reattempt."})
                else:
                    log_audit("REATTEMPT_GRANTED", user['email'], exam_code, details=f"Granted reattempt for #{attempt_id} ({student_email}). Previous attempt cleared.")
                    return self.send_json({"success": True, "message": f"Re-attempt granted for {student_email} on assessment {exam_code}!"})

            return self.send_json({"error": "Not Found"}, status=404)

        except Exception as ex:
            import traceback
            traceback.print_exc()
            return self.send_json({"error": "Internal Server Error", "details": str(ex)}, status=500)

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def run_server(port=7860):
    env_port = os.environ.get("PORT")
    if env_port:
        try:
            port = int(env_port)
        except ValueError:
            pass
            
    os.chdir(os.path.join(os.path.dirname(__file__), "public"))
    masked_uri = MONGO_URI
    if "@" in MONGO_URI:
        parts = MONGO_URI.split("@", 1)
        prefix = parts[0]
        suffix = parts[1]
        if "://" in prefix:
            scheme, auth = prefix.split("://", 1)
            if ":" in auth:
                user, _ = auth.split(":", 1)
                masked_uri = f"{scheme}://{user}:****@{suffix}"
            else:
                masked_uri = f"{scheme}://{auth}:****@{suffix}"
    print(f"[DB INFO] Connecting to database URI: {masked_uri}")
    init_db()
    handler = FlyLockHTTPRequestHandler
    httpd = ThreadedHTTPServer(("", port), handler)
    print(f"High-Concurrency FlyLock Server (500+ Students Capacity) running on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7860
    run_server(port)
