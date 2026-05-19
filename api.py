from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import random
from dotenv import load_dotenv
from google import genai
from datetime import date

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DATABASE_URL = "postgresql://postgres.nhdcxefdkcehytaciweq:iGmZDj.42XS&Gnk@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

client = genai.Client(api_key=GOOGLE_API_KEY) if GOOGLE_API_KEY else None

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# دالة الاتصال بالسحابة
# ==========================================
def get_db_connection():
    try:
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    except Exception as e:
        print("❌ خطأ في الاتصال بقاعدة البيانات:", e)
        raise e

# ==========================================
# بناء الجداول تلقائياً في السحابة عند التشغيل
# ==========================================
@app.on_event("startup")
def startup_event():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # بناء جدول المستخدمين
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            full_name TEXT,
            phone TEXT,
            otp TEXT,
            role TEXT,
            password TEXT,
            staff_id TEXT,
            belongs_to_doctor_id TEXT
        )
    ''')
    
    # بناء جدول تفاصيل الأطباء
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doctors_info (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            specialty TEXT,
            price INTEGER,
            city TEXT,
            address TEXT,
            image_url TEXT,
            is_active BOOLEAN DEFAULT TRUE
        )
    ''')
    
    # التأكد من إضافة الأعمدة الجديدة إذا كان الجدول القديم موجود
    try:
        cursor.execute("ALTER TABLE doctors_info ADD COLUMN IF NOT EXISTS city TEXT")
        cursor.execute("ALTER TABLE doctors_info ADD COLUMN IF NOT EXISTS address TEXT")
        cursor.execute("ALTER TABLE doctors_info ADD COLUMN IF NOT EXISTS image_url TEXT")
        cursor.execute("ALTER TABLE doctors_info ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
    except:
        pass
    
    # بناء جدول الحجوزات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id SERIAL PRIMARY KEY,
            patient_name TEXT,
            patient_phone TEXT,
            doctor_id TEXT,
            date TEXT,
            time TEXT,
            badge_number INTEGER,
            status TEXT
        )
    ''')
    
    # إضافة حسابك (الأدمن) تلقائياً إذا ما كان موجود
    cursor.execute("SELECT id FROM users WHERE phone = '078405827151'")
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO users (full_name, phone, staff_id, password, role) 
            VALUES (%s, %s, %s, %s, %s)
        ''', ("المدير أمير", "078405827151", "078405827151", "158264", "admin"))
        print("✅ تم زرع حساب الأدمن بنجاح في السحابة!")
        
    conn.commit()
    conn.close()
    print("✅ تم الاتصال بالسحابة وبناء النظام بنجاح!")


# ==========================================
# النماذج (Models)
# ==========================================
class PatientOTPRequest(BaseModel):
    phone: str

class PatientVerifyRequest(BaseModel):
    phone: str
    otp: str

class StaffLoginRequest(BaseModel):
    staff_id: str  
    password: str

# 🟢 تم التحديث: إضافة المحافظة والعنوان والصورة للأدمن
class CreateStaffRequest(BaseModel):
    full_name: str
    phone: str              
    password: str           
    role: str               
    specialty: str = ""     
    price: int = 0          
    belongs_to_doctor_phone: str = "" 
    city: str = ""
    address: str = ""
    image_url: str = "https://cdn-icons-png.flaticon.com/512/3774/3774299.png"

class AdminControlRequest(BaseModel):
    target_phone: str
    new_password: str = ""
    new_phone: str = ""
    is_blocked: int = -1 

class SymptomRequest(BaseModel):
    symptoms: str

class AppointmentRequest(BaseModel):
    patient_name: str
    patient_phone: str
    doctor_phone: str 
    time: str

class UpdateStatusRequest(BaseModel):
    appointment_id: int
    status: str 


# ==========================================
# 1. نظام دخول المرضى (OTP)
# ==========================================
@app.post("/auth/patient/request_otp")
async def request_otp(request: PatientOTPRequest):
    try:
        generated_otp = str(random.randint(1000, 9999))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE phone = %s AND role = 'patient'", (request.phone,))
        user = cursor.fetchone()
        
        if user:
            cursor.execute("UPDATE users SET otp = %s WHERE phone = %s", (generated_otp, request.phone))
        else:
            cursor.execute("INSERT INTO users (full_name, phone, otp, role) VALUES (%s, %s, %s, 'patient')", ("مريض جديد", request.phone, generated_otp))
        
        conn.commit()
        conn.close()
        print(f"📱 [رسالة واتساب وهمية] الرمز: {generated_otp}")
        return {"success": True, "message": "تم إرسال رمز التحقق"}
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500)

@app.post("/auth/patient/verify_otp")
async def verify_otp(request: PatientVerifyRequest):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, full_name, phone, role FROM users WHERE phone = %s AND otp = %s AND role = 'patient'", (request.phone, request.otp))
        user = cursor.fetchone()
        
        if user:
            cursor.execute("UPDATE users SET otp = NULL WHERE phone = %s", (request.phone,))
            conn.commit()
            conn.close()
            return {"success": True, "user": {"id": user['id'], "full_name": user['full_name'], "phone": user['phone'], "role": user['role']}}
        conn.close()
        raise HTTPException(status_code=401, detail="الرمز غير صحيح")
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500)


# ==========================================
# 2. دخول الكادر
# ==========================================
@app.post("/auth/staff/login")
async def staff_login(request: StaffLoginRequest):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, full_name, phone, role, password, belongs_to_doctor_id FROM users WHERE (staff_id = %s OR phone = %s) AND role != 'patient'", (request.staff_id, request.staff_id))
        user = cursor.fetchone()
        conn.close()
        
        if user and user['password'] == request.password:
            return {
                "success": True, 
                "user": {
                    "id": user['id'], 
                    "full_name": user['full_name'], 
                    "phone": user['phone'],
                    "role": user['role'],
                    "doctor_phone": user['belongs_to_doctor_id'] 
                }
            }
        raise HTTPException(status_code=401, detail="البيانات غير صحيحة")
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500)


# ==========================================
# 3. لوحة الأدمن
# ==========================================
@app.post("/admin/create_staff")
async def create_staff(request: CreateStaffRequest):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO users (full_name, staff_id, phone, password, role, belongs_to_doctor_id)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        ''', (request.full_name, request.phone, request.phone, request.password, request.role, request.belongs_to_doctor_phone if request.role == 'secretary' else ""))
        
        user_id = cursor.fetchone()['id']
        
        if request.role == 'doctor':
            # 🟢 تم التحديث: حفظ المحافظة والعنوان عند إضافة الدكتور
            cursor.execute('''
                INSERT INTO doctors_info (user_id, specialty, price, city, address, image_url) 
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (user_id, request.specialty, request.price, request.city, request.address, request.image_url))
            
        conn.commit()
        conn.close()
        return {"success": True, "message": "تم إنشاء الحساب بنجاح"}
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="رقم الهاتف مسجل مسبقاً!")

@app.post("/admin/control_staff")
async def control_staff(request: AdminControlRequest):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if request.new_password:
            cursor.execute("UPDATE users SET password = %s WHERE phone = %s", (request.new_password, request.target_phone))
        if request.new_phone:
            cursor.execute("UPDATE users SET phone = %s, staff_id = %s WHERE phone = %s", (request.new_phone, request.new_phone, request.target_phone))
        if request.is_blocked == 1:
            cursor.execute("UPDATE users SET password = %s WHERE phone = %s", ("BLOCKED_" + str(random.randint(1000,9999)), request.target_phone))
        conn.commit()
        conn.close()
        return {"success": True, "message": "تم تحديث البيانات بنجاح"}
    except Exception as e:
        raise HTTPException(status_code=500)


# ==========================================
# 4. المواعيد
# ==========================================
@app.post("/appointments/add")
async def add_appointment(request: AppointmentRequest):
    try:
        today = str(date.today())
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM appointments WHERE doctor_id = %s AND date = %s", (request.doctor_phone, today))
        badge_number = cursor.fetchone()['count'] + 1
        
        cursor.execute('''
            INSERT INTO appointments (patient_name, patient_phone, doctor_id, date, time, badge_number, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'waiting')
        ''', (request.patient_name, request.patient_phone, request.doctor_phone, today, request.time, badge_number))
        conn.commit()
        conn.close()
        return {"success": True, "message": "تم تسجيل المراجع"}
    except Exception as e:
        raise HTTPException(status_code=500)

@app.get("/doctor/dashboard/{doctor_phone}")
async def get_doctor_dashboard(doctor_phone: str):
    try:
        today = str(date.today())
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT price FROM doctors_info WHERE user_id = (SELECT id FROM users WHERE phone = %s)", (doctor_phone,))
        doc_info = cursor.fetchone()
        price = doc_info['price'] if doc_info else 0
        
        cursor.execute("SELECT COUNT(*) as count FROM appointments WHERE doctor_id = %s AND date = %s AND status = 'entered'", (doctor_phone, today))
        patients_entered = cursor.fetchone()['count']
        total_revenue = patients_entered * price
        
        cursor.execute("SELECT id, patient_name, badge_number FROM appointments WHERE doctor_id = %s AND date = %s AND status = 'waiting'", (doctor_phone, today))
        waiting_patients = [{"id": row["id"], "name": row["patient_name"], "badge": row["badge_number"]} for row in cursor.fetchall()]
        conn.close()
        return {"success": True, "stats": {"patients_count": patients_entered, "total_revenue": total_revenue, "waiting_patients": waiting_patients}}
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500)

@app.get("/secretary/appointments/{doctor_phone}")
async def get_secretary_appointments(doctor_phone: str):
    try:
        today = str(date.today())
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, patient_name, patient_phone, time, badge_number, status FROM appointments WHERE date = %s AND doctor_id = %s ORDER BY badge_number ASC", (today, doctor_phone))
        appointments = [{"id": row["id"], "name": row["patient_name"], "phone": row["patient_phone"], "time": row["time"], "badge": row["badge_number"], "status": row["status"]} for row in cursor.fetchall()]
        conn.close()
        return {"success": True, "appointments": appointments}
    except Exception as e:
        raise HTTPException(status_code=500)

@app.post("/appointments/update_status")
async def update_status(request: UpdateStatusRequest):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE appointments SET status = %s WHERE id = %s", (request.status, request.appointment_id))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500)

# ==========================================
# 5. جلب الدكاترة لواجهة المريض
# ==========================================
@app.get("/doctors")
async def get_doctors(city: str = "الكل", specialty: str = "الكل", price_sort: str = "الافتراضي"):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 🟢 تم التحديث: سحب رقم هاتف الطبيب (u.phone as doctor_phone) حتى يشتغل الحجز
        query = '''
            SELECT u.id, u.full_name as name, u.phone as doctor_phone, d.specialty, COALESCE(d.city, 'غير محدد') as city, 
                   COALESCE(d.address, 'غير محدد') as address, d.price as fees, 
                   d.is_active, d.image_url
            FROM users u
            JOIN doctors_info d ON u.id = d.user_id
            WHERE u.role = 'doctor'
        '''
        params = []
        
        if city != "الكل":
            query += " AND d.city = %s"
            params.append(city)
            
        if specialty != "الكل":
            query += " AND d.specialty = %s"
            params.append(specialty)
            
        if price_sort == "الأقل سعراً":
            query += " ORDER BY d.price ASC"
        elif price_sort == "الأعلى سعراً":
            query += " ORDER BY d.price DESC"
            
        cursor.execute(query, params)
        doctors = cursor.fetchall()
        
        conn.close()
        return doctors
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500)

# ==========================================
# 6. الذكاء الاصطناعي
# ==========================================
@app.post("/ai/analyze")
async def analyze_symptoms(request: SymptomRequest):
    if not client: raise HTTPException(status_code=500)
    try:
        response = client.models.generate_content(model='gemini-1.5-flash', contents=f"أنت طبيب مساعد عراقي. مريض يشكو من: {request.symptoms}. اعطه نصائح بلهجة عراقية.")
        return {"success": True, "ai_suggestion": response.text}
    except Exception as e: raise HTTPException(status_code=500)