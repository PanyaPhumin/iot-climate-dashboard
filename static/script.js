let climateChart;
let buttonChart;

// ตัวแปรเก็บชื่อห้องที่ผู้ใช้กำลังเลือกดูอยู่ในปัจจุบัน (ค่าเริ่มต้นจะถูกตั้งอิงจากห้องแรกที่เจอใน Excel)
let currentSelectedRoom = null; 

// ถังเก็บประวัติแยกรายห้องเพื่อเอาไว้พล็อตระนาบกราฟเส้นแบบไม่ปนกัน
let roomHistoryData = {}; 

// ตัวแปรควบคุมประเภทข้อมูลที่จะโชว์บนกราฟเส้น ('hi', 'temp', 'humi')
let currentDataType = 'hi'; 

// 1. เริ่มต้นสร้างกราฟเปล่ามารอไว้
void function initCharts() {
    const ctxLine = document.getElementById('climateLineChart').getContext('2d');
    climateChart = new Chart(ctxLine, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'ดัชนีความร้อน (°C)', 
                data: [],
                borderColor: '#ff9f40',
                backgroundColor: 'rgba(255, 159, 64, 0.1)',
                tension: 0.3,
                fill: true
            }]
        },
        options: { 
            responsive: true, 
            maintainAspectRatio: false,
            // คุมสเกลแกน Y ให้โปร่ง กว้าง ไม่ไปกระจุกชนเพดานบนสุด
            scales: {
                y: {
                    beginAtZero: false,
                    suggestedMin: 20,
                    suggestedMax: 55,
                    grace: '10%'
                }
            },
            // 🟢 เปิดระบบซูมเข้า-ออก (ด้วยล้อเมาส์) และแพนเลื่อนซ้ายขวาในแกน X
            plugins: {
                zoom: {
                    // 🟢 1. กำหนดขอบเขต (Limits) การซูมและแพนให้กับแกน X
                    limits: {
                        x: {
                            minRange: 5 // 💡 ล็อกเป้า: ยอมให้ซูมเข้าได้มากที่สุดจนเหลือข้อมูลบนจอไม่น้อยกว่า 5 จุด
                        }
                    },
                    zoom: {
                        wheel: { enabled: true },  
                        pinch: { enabled: true },  
                        mode: 'x',                 
                    },
                    pan: {
                        enabled: true,             
                        mode: 'x',
                    }
                }
            }
        }
    });

    const ctxBar = document.getElementById('buttonClickBarChart').getContext('2d');
    buttonChart = new Chart(ctxBar, {
        type: 'bar',
        data: {
            labels: ['ช่วง 27-32°C (เฝ้าระวัง)', 'ช่วง 32-41°C (ระวังพิเศษ)', 'ช่วง 41-54°C (อันตราย)'],
            datasets: [{
                label: 'จำนวนครั้งที่คนกดปุ่มอึดอัด',
                data: [0, 0, 0],
                backgroundColor: ['#ffcd56', '#ff9f40', '#ff6384']
            }]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });
}();

// 2. ฟังก์ชันหลักในการดึงค่าและประมวลผลแยกห้อง
async function updateDashboardData() {
    try {
        const response = await fetch('/api/get_data');
        if (!response.ok) return;
        
        const data = await response.json();
        roomHistoryData = {};

        const roomContainer = document.getElementById('room-container');
        roomContainer.innerHTML = ""; 

        for (const [roomName, roomValue] of Object.entries(data.latest)) {
            if (!currentSelectedRoom) {
                currentSelectedRoom = roomName;
            }

            let badgeClass = "badge-safe";
            let badgeText = "ปกติ";
            let cardBorderColor = "#22c55e";

            if (roomValue.hi >= 41) {
                badgeClass = "badge-danger"; badgeText = "อันตราย"; cardBorderColor = "#ef4444";
            } else if (roomValue.hi >= 32) {
                badgeClass = "badge-warning"; badgeText = "เฝ้าระวัง"; cardBorderColor = "#eab308";
            }

            const isSelected = roomName === currentSelectedRoom ? "style='box-shadow: 0 0 10px rgba(30,41,59,0.3); transform: scale(1.02);'" : "";

            // 🟢 ปรับปรุง Code HTML ของการ์ด: เพิ่มปุ่มถังขยะลบข้อมูลประวัติ
            const cardHtml = `
                <div class="room-card" ${isSelected} onclick="selectRoom('${roomName}')" style="border-top: 5px solid ${cardBorderColor}; cursor: pointer; position: relative;">
                    <div class="room-header" style="display: flex; justify-content: space-between; align-items: center;">
                        <h3>🏠 ${roomName}</h3>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span class="badge ${badgeClass}">${badgeText}</span>
                            <button onclick="deleteRoomData(event, '${roomName}')" style="background: none; border: none; cursor: pointer; font-size: 1.1rem; padding: 4px; transition: transform 0.2s;" onmouseover="this.style.transform='scale(1.2)'" onmouseout="this.style.transform='scale(1)'" title="ล้างข้อมูลประวัติห้องนี้">🗑️</button>
                        </div>
                    </div>
                    <div class="room-body">
                        <div class="data-row"><span>อุณหภูมิ:</span> <strong>${roomValue.temp} °C</strong></div>
                        <div class="data-row"><span>ความชื้น:</span> <strong>${roomValue.humi} %</strong></div>
                        <div class="data-row heat-index-row"><span>ดัชนีความร้อน:</span> <strong>${roomValue.hi} °C</strong></div>
                    </div>
                </div>
            `;
            roomContainer.innerHTML += cardHtml;
        }

        // รีเฟรชหน้าจอกราฟเส้น
        refreshLineChart();

        // อัปเดตกราฟแท่งสถิติปุ่มกด (รวมทุกห้องตามเดิม)
        buttonChart.data.datasets[0].data = [
            data.button_stats.caution,
            data.button_stats.extreme_caution,
            data.button_stats.danger
        ];
        buttonChart.update();

    } catch (error) {
        console.error("Error updating dashboard:", error);
    }
}

// 3. ฟังก์ชันสลับห้องเมื่อผู้ใช้คลิกเลือกการ์ดห้อง
function selectRoom(roomName) {
    currentSelectedRoom = roomName;
    updateDashboardData();
}

// 4. ฟังก์ชันสลับประเภทข้อมูล (ปุ่ม Heat Index, อุณหภูมิ, ความชื้น)
function switchDataType(type) {
    currentDataType = type;
    const buttons = document.querySelectorAll('.btn-toggle');
    buttons.forEach(btn => btn.classList.remove('active'));
    
    const event = window.event;
    if(event) event.target.classList.add('active');

    refreshLineChart();
}

// 5. ฟังก์ชันสั่งวาดเส้นกราฟใหม่ตามห้องและประเภทข้อมูลที่ถูกเลือก
async function refreshLineChart() {
    if (!currentSelectedRoom) return;

    document.getElementById('line-chart-title').innerText = `📈 แนวโน้มสภาพอากาศ: ห้อง ${currentSelectedRoom}`;

    try {
        const response = await fetch(`/api/get_data?room=${encodeURIComponent(currentSelectedRoom)}`);
        const data = await response.json();
        
        climateChart.data.labels = data.chart_timeline;

        if (currentDataType === 'temp') {
            climateChart.data.datasets[0].label = `อุณหภูมิ (${currentSelectedRoom}) (°C)`;
            climateChart.data.datasets[0].data = data.chart_temp;
            climateChart.data.datasets[0].borderColor = '#ff6384';
            climateChart.data.datasets[0].backgroundColor = 'rgba(255, 99, 132, 0.1)';
        } else if (currentDataType === 'humi') {
            climateChart.data.datasets[0].label = `ความชื้น (${currentSelectedRoom}) (%)`;
            climateChart.data.datasets[0].data = data.chart_humi;
            climateChart.data.datasets[0].borderColor = '#36a2eb';
            climateChart.data.datasets[0].backgroundColor = 'rgba(54, 162, 235, 0.1)';
        } else { 
            climateChart.data.datasets[0].label = `ดัชนีความร้อน (${currentSelectedRoom}) (°C)`;
            climateChart.data.datasets[0].data = data.chart_hi;
            climateChart.data.datasets[0].borderColor = '#ff9f40';
            climateChart.data.datasets[0].backgroundColor = 'rgba(255, 159, 64, 0.1)';
        }
        climateChart.update();
    } catch (e) {
        console.error(e);
    }
}

async function deleteRoomData(event, roomName) {
    // ป้องกันไม่ให้ระบบไปคลิกเลือกการ์ดห้องสลับหน้ากราฟตอนกดปุ่มลบ
    event.stopPropagation(); 
    
    // แจ้งเตือนยืนยันก่อนลบจริง
    if (!confirm(`คุณแน่ใจใช่ไหมที่จะลบประวัติข้อมูลทั้งหมดของ "ห้อง ${roomName}"? (จะเหลือไว้เพียงค่าล่าสุดเท่านั้น)`)) {
        return;
    }

    try {
        const response = await fetch('/api/delete_room_data', {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ room_name: roomName })
        });

        const result = await response.json();
        
        if (response.ok) {
            alert(`ล้างข้อมูลประวัติของห้อง ${roomName} เรียบร้อยแล้ว!`);
            // สั่งอัปเดตหน้าจอและพล็อตเส้นกราฟใหม่ทันที
            updateDashboardData();
        } else {
            alert(`เกิดข้อผิดพลาด: ${result.message}`);
        }
    } catch (error) {
        console.error("Error deleting room data:", error);
        alert("ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์เพื่อลบข้อมูลได้");
    }
}

updateDashboardData();
setInterval(updateDashboardData, 10000);