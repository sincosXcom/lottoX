import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import requests
import time
import uuid
from streamlit.runtime.scriptrunner import get_script_run_ctx
from collections import Counter

# ================== 页面配置 ==================
st.set_page_config(page_title="彩票数据中心 | 最新开奖", layout="wide")

# ================== Redis 在线人数（带前缀） ==================
APP_PREFIX = "lotto_data"

class RedisClient:
    def __init__(self, url, token):
        self.url = url.rstrip('/')
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "text/plain"
        })

    def setex(self, key, ttl, value):
        prefixed_key = f"{APP_PREFIX}:{key}"
        url = f"{self.url}/set/{prefixed_key}?EX={ttl}"
        resp = self.session.post(url, data=str(value))
        return resp.ok

    def sadd(self, set_name, member):
        prefixed_set = f"{APP_PREFIX}:{set_name}"
        url = f"{self.url}/sadd/{prefixed_set}"
        resp = self.session.post(url, data=member)
        return resp.ok

    def scard(self, set_name):
        prefixed_set = f"{APP_PREFIX}:{set_name}"
        url = f"{self.url}/scard/{prefixed_set}"
        resp = self.session.get(url)
        if resp.ok:
            return resp.json().get("result", 0)
        return 0

@st.cache_resource
def get_redis():
    return RedisClient(st.secrets["redis"]["url"], st.secrets["redis"]["token"])

def get_user_id():
    ctx = get_script_run_ctx()
    if ctx and ctx.session_id:
        return ctx.session_id
    if "user_id" not in st.session_state:
        st.session_state.user_id = str(uuid.uuid4())
    return st.session_state.user_id

def update_online_status():
    try:
        r = get_redis()
        uid = get_user_id()
        r.setex(f"user:{uid}", 300, time.time())
        r.sadd("online_users_set", uid)
    except Exception:
        pass

def get_online_count():
    try:
        r = get_redis()
        return r.scard("online_users_set")
    except:
        return 0

# ================== Google Sheets 数据加载 ==================
@st.cache_resource
def get_gsheet_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(st.secrets["google"], scopes=scopes)
    return gspread.authorize(creds)

@st.cache_data(ttl=3600)
def load_lottery_data(sheet_name, expected_columns):
    try:
        client = get_gsheet_client()
        spreadsheet_id = st.secrets["google"]["spreadsheet_id"]
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        all_data = worksheet.get_all_values()
        if len(all_data) < 2:
            return pd.DataFrame(columns=expected_columns)
        headers = all_data[0]
        rows = all_data[1:]
        df = pd.DataFrame(rows, columns=headers)
        existing_cols = [col for col in expected_columns if col in df.columns]
        df = df[existing_cols]
        if "issue" in df.columns:
            df["issue"] = pd.to_numeric(df["issue"], errors="coerce")
            df = df.dropna(subset=["issue"])
            df = df.sort_values("issue", ascending=True).reset_index(drop=True)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df
    except Exception as e:
        st.error(f"加载 {sheet_name} 数据失败: {str(e)}")
        return pd.DataFrame()

# ================== VIP 授权验证 ==================
def verify_card_from_sheets(user_code):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(st.secrets["google"], scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet_id = st.secrets["google"]["spreadsheet_id"]
        sh = client.open_by_key(spreadsheet_id)
        ws = sh.worksheet("Cards")
        try:
            cell = ws.find(user_code, in_column=1)
        except gspread.exceptions.CellNotFound:
            return False, "授权码不存在"
        row_num = cell.row
        row_data = ws.row_values(row_num)
        if len(row_data) < 4:
            return False, "数据格式错误"
        days_str = row_data[1].strip()
        status = row_data[2].strip() if len(row_data) > 2 else ""
        active_time_str = row_data[3].strip() if len(row_data) > 3 else ""
        if status == "封禁":
            return False, "授权码已被封禁"
        now = datetime.now()
        if not active_time_str:
            ws.update_cell(row_num, 3, "已激活")
            ws.update_cell(row_num, 4, now.strftime("%Y-%m-%d %H:%M:%S"))
            return True, int(days_str)
        else:
            start = datetime.strptime(active_time_str, "%Y-%m-%d %H:%M:%S")
            used_days = (now - start).days
            remaining = int(days_str) - used_days
            if remaining > 0:
                return True, remaining
            else:
                return False, f"授权已过期 {remaining} 天"
    except Exception:
        return False, "验证服务异常，请稍后重试"

# ================== 彩种配置（已包含 type 字段，值为 "乐透" 或 "数字型"） ==================
LOTTERY_CONFIG = {
    "快乐8": {
        "sheet": "kl8",
        "columns": ["issue", "date"] + [f"n{i}" for i in range(1, 21)],
        "number_cols": [f"n{i}" for i in range(1, 21)],
        "type": "乐透",
        "red_count": 20, "blue_count": 0
    },
    "双色球": {
        "sheet": "ssq",
        "columns": ["issue", "date", "red1", "red2", "red3", "red4", "red5", "red6", "blue"],
        "number_cols": ["red1", "red2", "red3", "red4", "red5", "red6", "blue"],
        "type": "乐透",
        "red_count": 6, "blue_count": 1
    },
    "大乐透": {
        "sheet": "dlt",
        "columns": ["issue", "date", "red1", "red2", "red3", "red4", "red5", "blue1", "blue2"],
        "number_cols": ["red1", "red2", "red3", "red4", "red5", "blue1", "blue2"],
        "type": "乐透",
        "red_count": 5, "blue_count": 2
    },
    "七乐彩": {
        "sheet": "qlc",
        "columns": ["issue", "date", "n1", "n2", "n3", "n4", "n5", "n6", "n7", "special"],
        "number_cols": ["n1", "n2", "n3", "n4", "n5", "n6", "n7", "special"],
        "type": "乐透",
        "red_count": 7, "blue_count": 1
    },
    "韩国乐透": {
        "sheet": "klotto",
        "columns": ["issue", "date", "n1", "n2", "n3", "n4", "n5", "n6", "special"],
        "number_cols": ["n1", "n2", "n3", "n4", "n5", "n6", "special"],
        "type": "乐透",
        "red_count": 6, "blue_count": 1
    },
    "福彩3D": {
        "sheet": "sd",
        "columns": ["issue", "date", "n1", "n2", "n3"],
        "number_cols": ["n1", "n2", "n3"],
        "type": "数字型",
        "red_count": 3, "blue_count": 0
    },
    "排列3": {
        "sheet": "p3",
        "columns": ["issue", "date", "n1", "n2", "n3"],
        "number_cols": ["n1", "n2", "n3"],
        "type": "数字型",
        "red_count": 3, "blue_count": 0
    },
    "七星彩": {
        "sheet": "qxc",
        "columns": ["issue", "date", "n1", "n2", "n3", "n4", "n5", "n6", "special"],
        "number_cols": ["n1", "n2", "n3", "n4", "n5", "n6", "special"],
        "type": "数字型",
        "red_count": 6, "blue_count": 1
    }
}

# ================== 辅助函数 ==================
def get_latest_issue_data(sheet_name, config):
    df = load_lottery_data(sheet_name, config["columns"])
    if df.empty:
        return None, None, None
    latest = df.iloc[-1]
    issue = latest["issue"] if "issue" in latest else None
    date_val = latest["date"] if "date" in latest else None
    if isinstance(date_val, pd.Timestamp):
        date_str = date_val.strftime("%Y-%m-%d")
    else:
        date_str = str(date_val) if date_val else ""
    numbers = []
    for col in config["number_cols"]:
        val = latest[col]
        if pd.notna(val):
            numbers.append(str(int(val)) if isinstance(val, float) else str(val))
        else:
            numbers.append("?")
    return numbers, issue, date_str

def render_lottery_card(title, issue, date_str, numbers, config):
    red_count = config.get("red_count", len(numbers))
    blue_count = config.get("blue_count", 0)
    if red_count > len(numbers):
        red_count = len(numbers)
        blue_count = 0
    red_numbers = numbers[:red_count]
    blue_numbers = numbers[red_count:red_count+blue_count] if blue_count > 0 else []
    ball_html = ""
    for n in red_numbers:
        ball_html += f'<div class="number-ball red-ball">{n}</div>'
    for n in blue_numbers:
        ball_html += f'<div class="number-ball blue-ball">{n}</div>'
    card = f"""
    <div class="lottery-card">
        <div class="card-title">{title}</div>
        <div class="card-issue">期号: {issue} | {date_str}</div>
        <div class="ball-container">{ball_html}</div>
    </div>
    """
    return card

def render_all_latest():
    st.markdown("## 🎯 最新开奖结果")
    # 注意：字典键与 config["type"] 的值完全一致（"乐透" / "数字型"）
    lottery_groups = {"乐透": [], "数字型": []}
    for name, config in LOTTERY_CONFIG.items():
        numbers, issue, date_str = get_latest_issue_data(config["sheet"], config)
        if numbers is None:
            continue
        typ = config["type"]   # 值为 "乐透" 或 "数字型"
        lottery_groups[typ].append((name, issue, date_str, numbers, config))
    
    st.markdown("""
    <style>
    .lottery-card {
        background: #f8fafc;
        border-radius: 20px;
        padding: 16px;
        margin-bottom: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        transition: 0.2s;
        border-left: 6px solid #4b6cb7;
    }
    .card-title {
        font-size: 1.4rem;
        font-weight: bold;
        color: #1e293b;
        margin-bottom: 6px;
    }
    .card-issue {
        font-size: 0.85rem;
        color: #64748b;
        margin-bottom: 12px;
    }
    .ball-container {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 8px;
    }
    .number-ball {
        display: inline-block;
        width: 40px;
        height: 40px;
        line-height: 40px;
        text-align: center;
        border-radius: 50%;
        font-weight: bold;
        font-size: 16px;
        color: white;
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    }
    .red-ball {
        background: linear-gradient(135deg, #ef4444, #b91c1c);
    }
    .blue-ball {
        background: linear-gradient(135deg, #3b82f6, #1e3a8a);
    }
    </style>
    """, unsafe_allow_html=True)
    
    if lottery_groups["乐透"]:
        st.subheader("🎲 乐透型")
        cols = st.columns(2)
        for idx, (name, issue, date_str, numbers, config) in enumerate(lottery_groups["乐透"]):
            with cols[idx % 2]:
                card = render_lottery_card(name, issue, date_str, numbers, config)
                st.markdown(card, unsafe_allow_html=True)
    
    if lottery_groups["数字型"]:
        st.subheader("🔢 数字型")
        cols = st.columns(3)
        for idx, (name, issue, date_str, numbers, config) in enumerate(lottery_groups["数字型"]):
            with cols[idx % 3]:
                card = render_lottery_card(name, issue, date_str, numbers, config)
                st.markdown(card, unsafe_allow_html=True)

# ================== 主界面 ==================
def main():
    update_online_status()
    
    st.sidebar.title("🎰 彩票数据中心")
    announcement = "🎯 欢迎使用彩票数据中心 | 数据每日更新 | VIP解锁高阶分析"
    st.sidebar.markdown(
        f"""
        <div style="background-color:#f0f2f6; padding:6px; border-radius:8px; overflow:hidden; white-space:nowrap;">
            <div style="display:inline-block; animation: scroll-left 12s linear infinite;">
                {announcement}
            </div>
        </div>
        <style>
            @keyframes scroll-left {{
                0% {{ transform: translateX(100%); }}
                100% {{ transform: translateX(-100%); }}
            }}
        </style>
        """,
        unsafe_allow_html=True
    )
    st.sidebar.divider()
    st.sidebar.subheader("📊 数据统计")
    st.sidebar.info("当前展示所有彩种最新一期开奖结果")
    st.sidebar.divider()
    st.sidebar.markdown(f"👥 当前在线: **{get_online_count()}**")
    
    render_all_latest()
    
    st.markdown("---")
    st.subheader("🔓 VIP 高阶分析")
    
    if "vip_unlocked" not in st.session_state:
        st.session_state.vip_unlocked = False
        st.session_state.vip_days_left = 0
    
    if not st.session_state.vip_unlocked:
        st.markdown(
            """
            <div style="background-color:#d4edda; padding:10px 15px; border-radius:8px; border-left:4px solid #28a745; margin-bottom:15px;">
                🔓 该区域需解锁高阶权限，请输入授权码：
            </div>
            """,
            unsafe_allow_html=True
        )
        col1, col2 = st.columns([2, 1])
        with col1:
            auth_code = st.text_input("", placeholder="请输入授权码", type="password", key="vip_code", label_visibility="collapsed")
        with col2:
            if st.button("激活 VIP", use_container_width=True):
                ok, msg = verify_card_from_sheets(auth_code)
                if ok:
                    st.session_state.vip_unlocked = True
                    st.session_state.vip_days_left = msg
                    st.success(f"解锁成功！剩余 {msg} 天")
                    st.rerun()
                else:
                    st.error(msg)
    else:
        st.success(f"🌟 VIP 已激活，剩余 {st.session_state.vip_days_left} 天")
        selected_lottery = st.selectbox("请选择彩种进行分析", list(LOTTERY_CONFIG.keys()))
        config = LOTTERY_CONFIG[selected_lottery]
        with st.spinner(f"加载 {selected_lottery} 数据..."):
            df = load_lottery_data(config["sheet"], config["columns"])
        if not df.empty:
            all_numbers = []
            for col in config["number_cols"]:
                if col in df.columns:
                    all_numbers.extend(df[col].dropna().astype(int).tolist())
            if all_numbers:
                counter = Counter(all_numbers)
                top10 = counter.most_common(10)
                st.markdown(f"**🔥 {selected_lottery} 历史热号 TOP 10**")
                cols = st.columns(10)
                for i, (num, cnt) in enumerate(top10):
                    with cols[i]:
                        st.metric(label=str(num), value=int(cnt))
                st.markdown(f"**❄️ {selected_lottery} 历史冷号（出现次数最少）**")
                bottom10 = counter.most_common()[-10:]
                cols2 = st.columns(10)
                for i, (num, cnt) in enumerate(bottom10):
                    with cols2[i]:
                        st.metric(label=str(num), value=int(cnt))
            else:
                st.info("无号码数据")
        else:
            st.info("暂无数据，请稍后重试")
        
        if st.button("退出 VIP", use_container_width=True):
            st.session_state.vip_unlocked = False
            st.rerun()

if __name__ == "__main__":
    main()
