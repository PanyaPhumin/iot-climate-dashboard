from flask import Flask, request, jsonify, render_template
import os
import math
import psycopg2  # 🟢 ตัวเชื่อมต่อฐานข้อมูล PostgreSQL
from psycopg2.extras import RealDictCursor  # ช่วยให้แปลงข้อมูล SQL เป็น Dictionary ง่ายขึ้น

app = Flask(__name__)

# 🟢 1. รับค่าเส้นทางเชื่อมต่อฐานข้อมูลจากระบบของ Render
# หากรันในคอมตัวเองและยังไม่ได้ตั้งค่า ระบบจะดีดกลับมาหา localhost อัตโนมัติเพื่อป้องกันโค้ดพัง
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/postgres')

def get_db_connection():
    """ฟังก์ชันเปิดสายเชื่อมต่อเข้าสู่ฐานข้อมูล PostgreSQL"""
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    """🟢 2. ฟังก์ชันสร้างตารางเก็บข้อมูลทดแทนไฟล์ Excel อัตโนมัติเมื่อเปิดเซิร์ฟเวอร์ครั้งแรก"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # สร้างตารางประวัติสภาพอากาศ (ทดแทนแผ่นงานหลัก in Excel)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS climate_logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                room_name VARCHAR(100) NOT NULL,
                temperature REAL NOT NULL,
                humidity REAL NOT NULL,
                heat_index REAL NOT NULL,
                button_pressed INT DEFAULT 0
            );
        ''')
        
        # สร้างตารางเก็บบันทึกสถิติปุ่มกดอึดอัดแยกตามกลุ่ม
        cur.execute('''
            CREATE TABLE IF NOT EXISTS button_stats (
                category VARCHAR(50) PRIMARY KEY,
                click_count INT DEFAULT 0
            );
        ''')
        
        # ใส่ค่าตั้งต้นให้กับกลุ่มปุ่มกด หากยังไม่มีข้อมูลอยู่ในฐานข้อมูล
        cur.execute('''
            INSERT INTO button_stats (category, click_count)
            VALUES ('caution', 0), ('extreme_caution', 0), ('danger', 0)
            ON CONFLICT (category) DO NOTHING;
        ''')
        
        conn.commit()
        cur.close()
        conn.close()
        print("✨ [Database] initialized and tables are ready.")
    except Exception as e:
        print(f"⚠️ [Database Init Warning]: {str(e)}")

# 🌟 🟢 ดึงคำสั่ง init_db ออกมานอก __main__ เพื่อให้ทำงานอย่างถูกต้องเมื่ออยู่บน Render (Gunicorn)
init_db()

@app.route('/')
def dashboard():
    return render_template('index.html')

@app.route('/api/data', methods=['POST'])
def receive_data():
    """🟢 3. พาร์ทรับข้อมูลยิงเข้ามาจากบอร์ด ESP32 ปรับปรุงลอจิก Rollback ป้องกันฐานข้อมูลล็อก"""
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data received"}), 400

    room = data.get("room", "Unknown")
    temp = float(data.get("temp", 0))
    humi = float(data.get("humi", 0))
    btn = int(data.get("button", 0))  # 0 = รอบปกติ, 1 = มีการกดปุ่ม
    heat_index = calculate_noaa_heat_index(temp, humi)

    # จัดการเรื่องระบบเวลาซิงก์
    esp_timestamp = data.get("timestamp")
    
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # ลอจิกการบันทึกข้อมูลแบบระบุเวลา หรือ อิงตามเวลาปัจจุบันบน Server
        if esp_timestamp and int(esp_timestamp) != 0:
            try:
                # ใช้ฟังก์ชัน to_timestamp ของ PostgreSQL แปลงค่า Epoch วินาทีได้ตรงๆ เลย
                cur.execute('''
                    INSERT INTO climate_logs (timestamp, room_name, temperature, humidity, heat_index, button_pressed)
                    VALUES (to_timestamp(%s), %s, %s, %s, %s, %s);
                ''', (int(esp_timestamp), room, temp, humi, heat_index, btn))
            except Exception:
                conn.rollback()  # 🚨 เคลียร์ Transaction เก่าที่เอ๋อก่อนหน้าออกไปก่อนเพื่อคืนสถานะปกติ
                cur.execute('''
                    INSERT INTO climate_logs (room_name, temperature, humidity, heat_index, button_pressed)
                    VALUES (%s, %s, %s, %s, %s);
                ''', (room, temp, humi, heat_index, btn))
        else:
            cur.execute('''
                INSERT INTO climate_logs (room_name, temperature, humidity, heat_index, button_pressed)
                VALUES (%s, %s, %s, %s, %s);
            ''', (room, temp, humi, heat_index, btn))

        # 🚨 อัปเดตนับสถิติปุ่มกดสะสมลงในตาราง SQL ทันทีหากมีการกดปุ่มแจ้งเข้ามา
        if btn == 1:
            category = None
            if 27 <= heat_index < 32:
                category = "caution"
            elif 32 <= heat_index < 41:
                category = "extreme_caution"
            elif 41 <= heat_index <= 54:
                category = "danger"

            if category:
                cur.execute('''
                    UPDATE button_stats 
                    SET click_count = click_count + 1 
                    WHERE category = %s;
                ''', (category,))

        conn.commit()
        print(f" Saved database row from {room}: Temp={temp}, Humi={humi}, Heat Index={heat_index}")
        return jsonify({"status": "success", "message": "Data saved to database"}), 200

    except Exception as e:
        conn.rollback()  # 🌟 หากส่วนใดส่วนหนึ่งพัง ให้สั่งม้วนกลับทันทีเพื่อไม่ให้ระบบค้างยาว
        print(f"❌ Database error in receive_data: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

def calculate_noaa_heat_index(temp_c, humidity):
    """ฟังก์ชันสูตรคำนวณดัชนีความร้อนของ NOAA คงไว้ตามโมเดลเดิม"""
    T = (temp_c * 9/5) + 32
    R = humidity
    
    if T < 80:
        HI_f = 0.5 * (T + 61.0 + ((T - 68.0) * 1.2) + (R * 0.094))
    else:
        HI_f = (-42.379 + 
                (2.04901523 * T) + 
                (10.14333127 * R) + 
                (-0.22475541 * T * R) + 
                (-0.00683783 * T * T) + 
                (-0.05481717 * R * R) + 
                (0.00122874 * T * T * R) + 
                (0.00085282 * T * R * R) + 
                (-0.00000199 * T * T * R * R))
        
        if R < 13 and (80 <= T <= 112):
            adjustment = ((13 - R) / 4) * math.sqrt((17 - abs(T - 95)) / 17)
            HI_f -= adjustment
        elif R > 85 and (80 <= T <= 87):
            adjustment = ((R - 85) / 10) * ((87 - T) / 5)
            HI_f += adjustment

    heat_index_c = (HI_f - 32) * 5/9
    return round(heat_index_c, 1)

@app.route('/api/get_data', methods=['GET'])
def get_data():
    """🟢 4. พาร์ทส่งข้อมูลออกไปแสดงผลบนแดชบอร์ด (ควบรวมดึงค่าประวัติและเรียลไทม์ผ่าน SQL)"""
    try:
        conn = get_db_connection()
        # แปลงข้อมูลคืนกลับออกมาเป็นแบบ Dictionary อัตโนมัติ
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 4.1 ดึงข้อมูลประวัติทั้งหมด เรียงลำดับจากเก่าไปใหม่เพื่อใช้ลากพล็อตเทรนด์กราฟเส้น
        cur.execute('''
            SELECT to_char(timestamp, 'HH24:MI') as time_str, temperature, humidity, heat_index 
            FROM climate_logs 
            ORDER BY timestamp ASC;
        ''')
        logs = cur.fetchall()

        # 4.2 ดึงเฉพาะข้อมูลแถวล่าสุดของแต่ละห้อง (DISTINCT ON) เพื่อเอามาใช้วาดกล่องสถานะเรียลไทม์บนหน้าบอร์ด
        cur.execute('''
            SELECT DISTINCT ON (room_name) room_name, temperature, humidity, heat_index
            FROM climate_logs
            ORDER BY room_name, timestamp DESC;
        ''')
        latest_rows = cur.fetchall()

        # 4.3 ดึงข้อมูลยอดสถิติปุ่มกดอึดอัด
        cur.execute('SELECT category, click_count FROM button_stats;')
        stats_rows = cur.fetchall()

        cur.close()
        conn.close()

        # 🛠️ 4.4 ประกอบร่างโครงสร้างข้อมูลให้เหมือนโครงสร้างเดิมของหน้าแดชบอร์ดเป๊ะๆ
        response_data = {
            "latest": {},
            "chart_timeline": [log['time_str'] for log in logs],
            "chart_temp": [log['temperature'] for log in logs],
            "chart_humi": [log['humidity'] for log in logs],
            "chart_hi": [log['heat_index'] for log in logs],
            "button_stats": {"caution": 0, "extreme_caution": 0, "danger": 0}
        }

        # ยัดข้อมูลเรียลไทม์รายห้อง
        for r in latest_rows:
            response_data["latest"][r['room_name']] = {
                "temp": r['temperature'],
                "humi": r['humidity'],
                "hi": r['heat_index']
            }

        # ยัดยอดปุ่มกดสะสม
        for s in stats_rows:
            response_data["button_stats"][s['category']] = s['click_count']

        return jsonify(response_data), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)