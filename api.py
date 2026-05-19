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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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
    
    # التأكد من إضافة عمود الإيميل إذا الجدول موجود مسبقاً
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
    except:
        pass

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

    # 🟢 تم التحديث: بناء جدول رموز الإيميل المؤقتة
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_otps (
            email TEXT PRIMARY KEY,
            otp TEXT
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
# 🟢 تم التحديث: نماذج تسجيل ودخول المرضى بالإيميل
class RequestEmailOTP(BaseModel):
    email: str

class PatientRegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str
    phone: str
    otp: str  # إجباري للتأكد من ملكية الإيميل

class PatientLoginRequest(BaseModel):
    email: str
    password: str

class StaffLoginRequest(BaseModel):
    staff_id: str  
    password: str

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
# 1. نظام دخول المرضى (الإيميل وكلمة السر)
# ==========================================
# 🟢 تم التحديث: دالة إرسال الرمز للإيميل
@app.post("/auth/patient/send_email_otp")
async def send_email_otp(request: RequestEmailOTP):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # فحص إذا الإيميل مسجل مسبقاً
        cursor.execute("SELECT id FROM users WHERE email = %s", (request.email,))
        if cursor.fetchone():
            conn.close()
            return {"success": False, "detail": "هذا البريد مسجل مسبقاً!"}
            
        generated_otp = str(random.randint(1000, 9999))
        
        # حفظ الرمز بالداتابيس
        cursor.execute('''
            INSERT INTO email_otps (email, otp) VALUES (%s, %s)
            ON CONFLICT (email) DO UPDATE SET otp = EXCLUDED.otp
        ''', (request.email, generated_otp))
        conn.commit()
        conn.close()

        # ⚠️ تنبيه: اكتب إيميلك وكلمة سر التطبيقات هنا ⚠️
        sender_email = os.getenv("SENDER_EMAIL")
        sender_password = os.getenv("SENDER_PASSWORD")
        
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = request.email
        msg['Subject'] = "رمز التحقق من عيادة SmartClinic"
        
        body = f"مرحباً بك!\n\nرمز التحقق الخاص بإنشاء حسابك هو: {generated_otp}\n\nيرجى عدم مشاركة الرمز مع أي شخص."
        msg.attach(MIMEText(body, 'plain'))
        
        # إرسال الإيميل
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        
        return {"success": True, "message": "تم إرسال رمز التحقق إلى بريدك"}
    except Exception as e:
        print("خطأ في إرسال الإيميل:", e)
        raise HTTPException(status_code=500, detail="فشل في إرسال البريد الإلكتروني")

# 🟢 تم التحديث: دالة التسجيل النهائية (بعد التأكد من الرمز)
@app.post("/auth/patient/register")
async def patient_register(request: PatientRegisterRequest):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. فحص هل الرمز صحيح؟
        cursor.execute("SELECT otp FROM email_otps WHERE email = %s", (request.email,))
        record = cursor.fetchone()
        
        if not record or record['otp'] != request.otp:
            conn.close()
            return {"success": False, "detail": "رمز التحقق غير صحيح أو منتهي الصلاحية"}
            
        # 2. إنشاء الحساب
        cursor.execute('''
            INSERT INTO users (full_name, email, password, phone, role) 
            VALUES (%s, %s, %s, %s, 'patient')
        ''', (request.full_name, request.email, request.password, request.phone))
        
        # 3. مسح الرمز بعد نجاح التسجيل
        cursor.execute("DELETE FROM email_otps WHERE email = %s", (request.email,))
        
        conn.commit()
        conn.close()
        return {"success": True, "message": "تم إنشاء الحساب بنجاح"}
    except Exception as e:
        print("خطأ في التسجيل:", e)
        raise HTTPException(status_code=500, detail="حدث خطأ في السيرفر")


@app.post("/auth/patient/login")
async def patient_login(request: PatientLoginRequest):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, full_name, phone, role FROM users WHERE email = %s AND password = %s AND role = 'patient'", (request.email, request.password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                "success": True, 
                "user": {
                    "id": user['id'], 
                    "full_name": user['full_name'], 
                    "phone": user['phone'], 
                    "role": user['role']
                }
            }
        
        return {"success": False, "detail": "البريد الإلكتروني أو كلمة المرور غير صحيحة"}
    except Exception as e:
        print("خطأ في الدخول:", e)
        raise HTTPException(status_code=500, detail="حدث خطأ في السيرفر")


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