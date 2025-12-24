"""
mine_web.py - Web-based Lightweight Mining Bot
รันบน localhost:5000 กด Start/Stop ผ่านเว็บเบราว์เซอร์

ระบบ:
- ID แรกไม่ขุด (ใช้เป็น CPU Helper เท่านั้น)
- ทุก ID รันพร้อมกัน (รอ cooldown แยกกัน)
- PoW ขุดทีละ 1 ID (ใช้ Semaphore ป้องกัน block)
"""

from flask import Flask, render_template_string, jsonify, request
import json
import threading
import time
import os
import subprocess
import requests
from datetime import datetime, timezone
from collections import deque

app = Flask(__name__)

# --- CONFIGURATION ---
ACCOUNTS_FILE = ".env"
RPC_ENDPOINTS = [
    'http://wax.qaraqol.com',
    'https://wax.greymass.com'
]

current_rpc_index = 0
FEDERATION_ACCOUNT = 'm.federation'
DEFAULT_LAND_ID = '1099512960590'

# --- GLOBALS ---
first_account_data = None
miners = {}
logs = deque(maxlen=200)
accounts_data = []
mining_semaphore = threading.Semaphore(3)  # ขุด PoW พร้อมกัน 3 ID


def get_rpc_url():
    return RPC_ENDPOINTS[current_rpc_index]


def switch_rpc():
    global current_rpc_index
    current_rpc_index = (current_rpc_index + 1) % len(RPC_ENDPOINTS)


def add_log(account, msg, level="info"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    logs.appendleft({"time": timestamp, "account": account, "msg": msg, "level": level})


def find_bounty_in_traces(traces):
    for t in traces:
        if t.get('act', {}).get('name') == 'logmint':
            data = t['act'].get('data', {})
            if 'bounty' in data:
                return data['bounty']
        if 'inline_traces' in t:
            res = find_bounty_in_traces(t['inline_traces'])
            if res:
                return res
    return None


class WebMiner(threading.Thread):
    def __init__(self, account_data):
        super().__init__()
        self.account_name = account_data['name']
        self.private_key = account_data['key']
        self.cooldown_config = account_data.get('cooldown', 2400)
        self.daemon = True
        self.running = True
        self.status = "Idle"
        
    def stop(self):
        self.running = False
        self.status = "Stopped"
        
    def run(self):
        """รันวนลูปไปเรื่อยๆ - รอ cooldown แยกกัน แต่ PoW ทีละตัว"""
        add_log(self.account_name, "เริ่มทำงาน", "info")
        while self.running:
            try:
                self.mine_process()
            except Exception as e:
                add_log(self.account_name, f"Error: {e}", "error")
            # รอ 5 วินาทีก่อนลูปใหม่
            for _ in range(5):
                if not self.running:
                    break
                time.sleep(1)
        add_log(self.account_name, "หยุดทำงาน", "warn")
        
    def get_table_rows(self, code, scope, table, lower_bound, limit=1):
        for _ in range(len(RPC_ENDPOINTS)):
            try:
                url = f"{get_rpc_url()}/v1/chain/get_table_rows"
                payload = {
                    "json": True, "code": code, "scope": scope,
                    "table": table, "lower_bound": lower_bound,
                    "upper_bound": lower_bound, "limit": limit
                }
                res = requests.post(url, json=payload, timeout=5)
                res.raise_for_status()
                return res.json()
            except:
                switch_rpc()
                time.sleep(0.2)
        return {}
        
    def get_miner_data(self):
        res = self.get_table_rows(FEDERATION_ACCOUNT, FEDERATION_ACCOUNT, 'miners', self.account_name)
        return res.get('rows', [None])[0]
        
    def do_work(self, last_mine_tx):
        """หา nonce - ลองใช้ C version ก่อน (เร็วกว่า) fallback เป็น JS"""
        payload = {"account": self.account_name, "lastMineTx": last_mine_tx}
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        # ลอง pow_worker (C version) - รองรับทั้ง Windows และ Linux
        if os.path.exists("pow_worker.exe"):
            cmd = ["pow_worker.exe"]
            worker_type = "C-Win"
        elif os.path.exists("pow_worker"):
            cmd = ["./pow_worker"]
            worker_type = "C-Linux"
        else:
            cmd = ["node", "pow_worker.js"]
            worker_type = "JS"
        
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, startupinfo=startupinfo
            )
            stdout, stderr = process.communicate(input=json.dumps(payload), timeout=180)
            
            if stderr and not stdout:
                raise Exception(f"PoW Error: {stderr}")
            result = json.loads(stdout)
            if result.get('success'):
                add_log(self.account_name, f"[{worker_type}] Nonce! ({result['iterations']:,} iters, {result['hashrate']:,} H/s)", "info")
                return result['nonce']
            else:
                raise Exception(result.get('error', 'Unknown'))
        except subprocess.TimeoutExpired:
            process.kill()
            raise Exception("PoW timeout (180s)")
            
    def push_transaction(self, actions, keys):
        global first_account_data
        key_list = keys.copy()
        
        if first_account_data and self.account_name != first_account_data['name']:
            payer_name = first_account_data['name']
            payer_key = first_account_data['key']
            if payer_key not in key_list:
                key_list.insert(0, payer_key)
            for action in actions:
                if 'authorization' not in action:
                    action['authorization'] = []
                if not action['authorization'] or action['authorization'][0].get('actor') != payer_name:
                    action['authorization'].insert(0, {"actor": payer_name, "permission": "active"})
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        for _ in range(3):
            try:
                payload = {"privateKeys": key_list, "rpcUrl": get_rpc_url(), "actions": actions}
                process = subprocess.Popen(
                    ['node', 'sign.js'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, startupinfo=startupinfo
                )
                stdout, stderr = process.communicate(input=json.dumps(payload))
                if stderr and not stdout:
                    raise Exception(f"Sign Error: {stderr}")
                result = json.loads(stdout)
                if result.get('success'):
                    return result
                else:
                    raise Exception(result.get('error', 'Unknown'))
            except json.JSONDecodeError:
                switch_rpc()
                time.sleep(2)
            except Exception as e:
                switch_rpc()
                raise e
        raise Exception("Failed after 3 retries")
        
    def mine_process(self):
        """ขั้นตอนขุด - Cooldown รอเอง, PoW ใช้ Semaphore"""
        self.status = "เช็ค Cooldown..."
        miner_data = self.get_miner_data()
        
        last_mine_tx = '0' * 64
        land_id = DEFAULT_LAND_ID
        
        if miner_data:
            last_mine_tx = miner_data.get('last_mine_tx', last_mine_tx)
            land_id = miner_data.get('current_land', land_id)
            
            if miner_data.get('last_mine'):
                last_mine_dt = datetime.fromisoformat(miner_data['last_mine'].split('.')[0]).replace(tzinfo=timezone.utc)
                now_dt = datetime.now(timezone.utc)
                diff = (now_dt - last_mine_dt).total_seconds()
                
                if diff < self.cooldown_config:
                    wait = self.cooldown_config - diff
                    end_time = time.time() + wait
                    while time.time() < end_time and self.running:
                        remaining = int(end_time - time.time())
                        mins = remaining // 60
                        secs = remaining % 60
                        self.status = f"รอ CD ({mins}m {secs}s)"
                        time.sleep(1)
                    if not self.running:
                        return
                    miner_data = self.get_miner_data()
                    if miner_data:
                        last_mine_tx = miner_data.get('last_mine_tx', last_mine_tx)
        
        # ใช้ Semaphore เพื่อขุดทีละ 1 ID
        self.status = "รอคิวขุด..."
        with mining_semaphore:
            # ดึง miner_data ใหม่ก่อน PoW (ป้องกัน Invalid hash)
            miner_data = self.get_miner_data()
            if miner_data:
                last_mine_tx = miner_data.get('last_mine_tx', last_mine_tx)
                land_id = miner_data.get('current_land', land_id)
            
            self.status = "⛏️ กำลังขุด (PoW)..."
            nonce = self.do_work(last_mine_tx)
            self.status = "📤 ส่ง Transaction..."
            
            actions = [{
                "account": FEDERATION_ACCOUNT,
                "name": "mine",
                "authorization": [{"actor": self.account_name, "permission": "active"}],
                "data": {"miner": self.account_name, "land_id": land_id, "nonce": nonce}
            }]
            
            try:
                res = self.push_transaction(actions, [self.private_key])
                mined_amount = "?"
                if 'traces' in res:
                    bounty = find_bounty_in_traces(res['traces'])
                    if bounty:
                        mined_amount = bounty
                add_log(self.account_name, f"✅ ขุดสำเร็จ! +{mined_amount}", "success")
                self.status = f"✅ +{mined_amount}"
            except Exception as e:
                if "MINE_TOO_SOON" in str(e):
                    add_log(self.account_name, "Mine Too Soon", "warn")
                else:
                    raise e


# --- HTML TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Alien Worlds Miner</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        
        header {
            text-align: center;
            padding: 30px 0;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            margin-bottom: 20px;
            backdrop-filter: blur(10px);
        }
        h1 {
            font-size: 2.5em;
            background: linear-gradient(90deg, #00d9ff, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }
        .subtitle { color: #888; font-size: 0.9em; }
        
        .controls {
            display: flex;
            gap: 15px;
            justify-content: center;
            margin: 20px 0;
            flex-wrap: wrap;
        }
        
        button {
            padding: 15px 40px;
            font-size: 1.1em;
            font-weight: bold;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .btn-start {
            background: linear-gradient(135deg, #00d9ff, #00ff88);
            color: #000;
            box-shadow: 0 4px 20px rgba(0,217,255,0.3);
        }
        .btn-start:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 30px rgba(0,217,255,0.5);
        }
        
        .btn-stop {
            background: linear-gradient(135deg, #ff4757, #ff6b81);
            color: #fff;
            box-shadow: 0 4px 20px rgba(255,71,87,0.3);
        }
        .btn-stop:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 30px rgba(255,71,87,0.5);
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        
        .stat-card {
            background: rgba(255,255,255,0.05);
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .stat-card h3 { color: #00d9ff; font-size: 2em; }
        .stat-card p { color: #888; font-size: 0.9em; margin-top: 5px; }
        
        .accounts-table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: rgba(255,255,255,0.03);
            border-radius: 15px;
            overflow: hidden;
        }
        .accounts-table th, .accounts-table td {
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .accounts-table th {
            background: rgba(0,217,255,0.1);
            color: #00d9ff;
            font-weight: 600;
        }
        .accounts-table tr:hover { background: rgba(255,255,255,0.03); }
        
        .logs {
            background: rgba(0,0,0,0.3);
            border-radius: 15px;
            padding: 20px;
            max-height: 300px;
            overflow-y: auto;
            font-family: 'Consolas', monospace;
            font-size: 0.85em;
        }
        .log-entry { padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
        .log-info { color: #00d9ff; }
        .log-success { color: #00ff88; }
        .log-warn { color: #ffa502; }
        .log-error { color: #ff4757; }
        .log-time { color: #666; }
        
        .status-running { color: #00ff88; }
        .status-stopped { color: #ff4757; }
        .status-waiting { color: #ffa502; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>⛏️ ALIEN WORLDS MINER</h1>
            <p class="subtitle">Lightweight Edition - CPU Helper from First ID</p>
        </header>
        
        <div class="controls">
            <button class="btn-start" onclick="startAll()">▶ START ALL</button>
            <button class="btn-stop" onclick="stopAll()">⏹ STOP ALL</button>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <h3 id="total-accounts">0</h3>
                <p>Total Accounts</p>
            </div>
            <div class="stat-card">
                <h3 id="running-count">0</h3>
                <p>Running</p>
            </div>
            <div class="stat-card">
                <h3 id="cpu-helper">-</h3>
                <p>CPU Helper ID</p>
            </div>
        </div>
        
        <h2 style="margin: 20px 0; color: #00d9ff;">📋 Accounts</h2>
        <table class="accounts-table">
            <thead>
                <tr>
                    <th>#</th>
                    <th>Account</th>
                    <th>Cooldown</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody id="accounts-body"></tbody>
        </table>
        
        <h2 style="margin: 20px 0; color: #00d9ff;">📜 Logs</h2>
        <div class="logs" id="logs-container"></div>
    </div>
    
    <script>
        function updateStatus() {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('total-accounts').textContent = data.total;
                    document.getElementById('running-count').textContent = data.running;
                    document.getElementById('cpu-helper').textContent = data.cpu_helper || '-';
                    
                    const tbody = document.getElementById('accounts-body');
                    tbody.innerHTML = '';
                    data.accounts.forEach((acc, i) => {
                        const statusClass = acc.running ? 
                            (acc.status.includes('รอ') ? 'status-waiting' : 'status-running') : 
                            'status-stopped';
                        tbody.innerHTML += `
                            <tr>
                                <td>${i+1}</td>
                                <td>${acc.name}</td>
                                <td>${acc.cooldown}s</td>
                                <td class="${statusClass}">${acc.status}</td>
                            </tr>
                        `;
                    });
                    
                    const logsDiv = document.getElementById('logs-container');
                    logsDiv.innerHTML = data.logs.map(l => 
                        `<div class="log-entry">
                            <span class="log-time">[${l.time}]</span> 
                            <span class="log-${l.level}">[${l.account}]</span> 
                            ${l.msg}
                        </div>`
                    ).join('');
                });
        }
        
        function startAll() {
            fetch('/api/start', { method: 'POST' })
                .then(() => updateStatus());
        }
        
        function stopAll() {
            fetch('/api/stop', { method: 'POST' })
                .then(() => updateStatus());
        }
        
        setInterval(updateStatus, 2000);
        updateStatus();
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/status')
def api_status():
    global miners, accounts_data, first_account_data
    
    accounts_info = []
    running_count = 0
    
    for acc in accounts_data:
        name = acc['name']
        miner = miners.get(name)
        is_running = miner.is_alive() if miner else False
        status = miner.status if miner else "Idle"
        
        if is_running:
            running_count += 1
            
        accounts_info.append({
            "name": name,
            "cooldown": acc['cooldown'],
            "running": is_running,
            "status": status
        })
    
    return jsonify({
        "total": len(accounts_data),
        "running": running_count,
        "cpu_helper": first_account_data['name'] if first_account_data else None,
        "accounts": accounts_info,
        "logs": list(logs)
    })


@app.route('/api/start', methods=['POST'])
def api_start():
    global miners, accounts_data, first_account_data
    
    # หยุด miner เก่าทั้งหมด
    for miner in miners.values():
        miner.stop()
    miners.clear()
    time.sleep(0.5)
    
    # ข้าม ID แรก (CPU Helper) เริ่มจาก ID ที่ 2
    mining_accounts = accounts_data[1:] if len(accounts_data) > 1 else []
    
    if not mining_accounts:
        add_log("SYSTEM", "ไม่มีบัญชีสำหรับขุด (ต้องมีมากกว่า 1 ID)", "error")
        return jsonify({"status": "error"})
    
    add_log("SYSTEM", f"🚀 เริ่ม {len(mining_accounts)} บัญชีพร้อมกัน!", "success")
    add_log("SYSTEM", f"CPU Helper: {first_account_data['name']}", "info")
    add_log("SYSTEM", f"⚡ PoW ขุดทีละ 1 ID (ป้องกัน block)", "info")
    
    # รันทุก ID พร้อมกัน (แต่ละ ID จะรอ cooldown ของตัวเอง)
    for i, acc in enumerate(mining_accounts):
        miner = WebMiner(acc)
        miners[acc['name']] = miner
        miner.start()
        # หน่วงเล็กน้อยระหว่างเริ่มแต่ละ ID (ป้องกัน rate limit)
        if i < 50:  # 50 แรกหน่วง 0.1s
            time.sleep(0.1)
        elif i % 10 == 0:
            time.sleep(0.05)
    
    add_log("SYSTEM", f"✅ ทุกบอทเริ่มทำงานแล้ว!", "success")
    return jsonify({"status": "ok"})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    global miners
    
    # หยุดทุก miner
    for miner in miners.values():
        miner.stop()
    
    add_log("SYSTEM", "⏹ หยุดทุกบอทแล้ว", "warn")
    return jsonify({"status": "ok"})


def load_accounts():
    global accounts_data, first_account_data
    
    raw_data = ''
    
    # 1. ลองอ่านจาก Environment Variable ก่อน (สำหรับ Koyeb)
    env_accounts = os.environ.get('BOT_ACCOUNTS', '')
    if env_accounts:
        add_log("SYSTEM", "อ่าน accounts จาก Environment Variable", "info")
        raw_data = env_accounts
    # 2. ลองอ่านจากไฟล์ bot_accounts_secret.txt
    elif os.path.exists('bot_accounts_secret.txt'):
        add_log("SYSTEM", "อ่าน accounts จาก bot_accounts_secret.txt", "info")
        with open('bot_accounts_secret.txt', 'r', encoding='utf-8') as f:
            raw_data = f.read()
    # 3. Fallback ไปที่ .env
    elif os.path.exists(ACCOUNTS_FILE):
        add_log("SYSTEM", f"อ่าน accounts จาก {ACCOUNTS_FILE}", "info")
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            raw_data = f.read()
    else:
        add_log("SYSTEM", "ไม่พบ accounts (ไม่มี ENV, bot_accounts_secret.txt, หรือ .env)", "error")
        return
    
    # ตรวจสอบรูปแบบ: comma-separated (account:key:cooldown,...)
    if ':' in raw_data and ',' in raw_data:
        add_log("SYSTEM", "ใช้รูปแบบ comma-separated (account:key:cooldown)", "info")
        entries = raw_data.split(',')
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(':')
            if len(parts) >= 2:
                cooldown = 2400
                if len(parts) >= 3:
                    try:
                        cooldown = int(parts[2].replace('s', ''))
                    except:
                        pass
                accounts_data.append({
                    'name': parts[0].strip(),
                    'key': parts[1].strip(),
                    'cooldown': cooldown
                })
    else:
        # รูปแบบเดิม: line-based (BOT_CONFIG=name key cooldown หรือ name key cooldown)
        lines = raw_data.split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            if line.startswith('BOT_CONFIG='):
                line = line.replace('BOT_CONFIG=', '')
            
            parts = line.split()
            if len(parts) >= 2:
                cooldown = 2400
                if len(parts) >= 3:
                    try:
                        cooldown = int(parts[2].replace('s', ''))
                    except:
                        pass
                accounts_data.append({
                    'name': parts[0].strip(),
                    'key': parts[1].strip(),
                    'cooldown': cooldown
                })
    
    if accounts_data:
        first_account_data = accounts_data[0]
        add_log("SYSTEM", f"CPU Helper: {first_account_data['name']}", "info")
        add_log("SYSTEM", f"โหลด {len(accounts_data)} บัญชี", "success")


if __name__ == '__main__':
    # Check dependencies
    if not os.path.exists("pow_worker.js"):
        print("ERROR: pow_worker.js not found!")
        exit(1)
    if not os.path.exists("sign.js"):
        print("ERROR: sign.js not found!")
        exit(1)
    
    load_accounts()
    
    # Auto-start mining หลังจากโหลด accounts
    def auto_start():
        time.sleep(3)  # รอให้ Flask พร้อม
        if accounts_data and len(accounts_data) > 1:
            add_log("SYSTEM", "🚀 Auto-Start Mining...", "success")
            # เริ่มขุดอัตโนมัติ
            mining_accounts = accounts_data[1:]
            for i, acc in enumerate(mining_accounts):
                miner = WebMiner(acc)
                miners[acc['name']] = miner
                miner.start()
                if i < 50:
                    time.sleep(0.1)
                elif i % 10 == 0:
                    time.sleep(0.05)
            add_log("SYSTEM", f"✅ Auto-started {len(mining_accounts)} บัญชี", "success")
    
    # รัน auto-start ใน thread แยก
    threading.Thread(target=auto_start, daemon=True).start()
    
    print("\n" + "="*50)
    print("  ALIEN WORLDS MINER - WEB INTERFACE")
    print("  เปิดเบราว์เซอร์ไปที่: http://localhost:8000")
    print("  🚀 Auto-Start: เปิดใช้งาน")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=8000, debug=False, threaded=True)

