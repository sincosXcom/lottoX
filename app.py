import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import requests
import time
import uuid
from streamlit.runtime.scriptrunner import get_script_run_ctx
from collections import Counter

st.set_page_config(page_title="LOTTOX彩票中心 | LOTTOX", layout="wide")

# ================== 时区处理：北京时间 ==================
def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

# ================== Redis 在线人数 ==================
APP_PREFIX = "lotto_data"

class RedisClient:
    def __init__(self, url, token):
        self.url = url.rstrip('/')
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}", "Content-Type": "text/plain"})
    def setex(self, key, ttl, value):
        url = f"{self.url}/set/{APP_PREFIX}:{key}?EX={ttl}"
        return self.session.post(url, data=str(value)).ok
    def sadd(self, set_name, member):
        url = f"{self.url}/sadd/{APP_PREFIX}:{set_name}"
        return self.session.post(url, data=member).ok
    def scard(self, set_name):
        url = f"{self.url}/scard/{APP_PREFIX}:{set_name}"
        resp = self.session.get(url)
        return resp.json().get("result", 0) if resp.ok else 0

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
    except:
        pass

def get_online_count():
    try:
        return get_redis().scard("online_users_set")
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

# ================== VIP 授权 ==================
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
        now = get_beijing_time()  # 使用北京时间
        if not active_time_str:
            ws.update_cell(row_num, 3, "已激活")
            ws.update_cell(row_num, 4, now.strftime("%Y-%m-%d %H:%M:%S"))
            return True, int(days_str)
        else:
            start = datetime.strptime(active_time_str, "%Y-%m-%d %H:%M:%S")
            used = (now - start).days
            remaining = int(days_str) - used
            if remaining > 0:
                return True, remaining
            else:
                return False, f"授权已过期 {remaining} 天"
    except Exception:
        return False, "验证服务异常，请稍后重试"

# ================== 彩种配置 ==================
LOTTERY_CONFIG = {
    "双色球": {"sheet": "ssq", "columns": ["issue", "date", "red1","red2","red3","red4","red5","red6","blue"], "number_cols": ["red1","red2","red3","red4","red5","red6","blue"], "red_count": 6, "blue_count": 1},
    "大乐透": {"sheet": "dlt", "columns": ["issue", "date", "red1","red2","red3","red4","red5","blue1","blue2"], "number_cols": ["red1","red2","red3","red4","red5","blue1","blue2"], "red_count": 5, "blue_count": 2},
    "快乐8": {"sheet": "kl8", "columns": ["issue", "date"] + [f"n{i}" for i in range(1,21)], "number_cols": [f"n{i}" for i in range(1,21)], "red_count": 20, "blue_count": 0},
    "排列3": {"sheet": "p3", "columns": ["issue", "date", "n1","n2","n3"], "number_cols": ["n1","n2","n3"], "red_count": 3, "blue_count": 0},
    "福彩3D": {"sheet": "sd", "columns": ["issue", "date", "n1","n2","n3"], "number_cols": ["n1","n2","n3"], "red_count": 3, "blue_count": 0},
    "排列5": {"sheet": "p5", "columns": ["issue", "date", "n1","n2","n3","n4","n5"], "number_cols": ["n1","n2","n3","n4","n5"], "red_count": 5, "blue_count": 0},
    "七乐彩": {"sheet": "qlc", "columns": ["issue", "date", "n1","n2","n3","n4","n5","n6","n7","special"], "number_cols": ["n1","n2","n3","n4","n5","n6","n7","special"], "red_count": 7, "blue_count": 1},
    "七星彩": {"sheet": "qxc", "columns": ["issue", "date", "n1","n2","n3","n4","n5","n6","special"], "number_cols": ["n1","n2","n3","n4","n5","n6","special"], "red_count": 6, "blue_count": 1},
}

DISPLAY_ORDER = ["大乐透", "七星彩", "排列3", "排列5", "双色球", "福彩3D", "快乐8", "七乐彩"]

LOTTERY_WEEKDAYS = {
    "大乐透": "每周一,三,六开奖",
    "七星彩": "每周二,五,日开奖",
    "排列3": "每天开奖",
    "排列5": "每天开奖",
    "双色球": "每周二,四,日开奖",
    "福彩3D": "每天开奖",
    "快乐8": "每天开奖",
    "七乐彩": "每周一,三,五开奖",
}

# ================== 最新开奖展示 ==================
def get_latest_issue_data(sheet_name, config):
    df = load_lottery_data(sheet_name, config["columns"])
    if df.empty:
        return None, None, None
    latest = df.iloc[-1]
    issue = latest["issue"] if "issue" in latest else None
    date_val = latest["date"] if "date" in latest else None
    date_str = date_val.strftime("%Y-%m-%d") if isinstance(date_val, pd.Timestamp) else str(date_val) if date_val else ""
    numbers = [str(int(v)) if isinstance(v, float) else str(v) for v in [latest[col] for col in config["number_cols"] if col in latest] if pd.notna(v)]
    return numbers, issue, date_str

def render_lottery_card(title, issue, date_str, numbers, config):
    red_count = config.get("red_count", len(numbers))
    blue_count = config.get("blue_count", 0)
    if red_count > len(numbers):
        red_count = len(numbers)
        blue_count = 0
    red_numbers = numbers[:red_count]
    blue_numbers = numbers[red_count:red_count+blue_count] if blue_count > 0 else []
    
    red_balls = "".join([f'<div class="number-ball red-ball">{n}</div>' for n in red_numbers])
    blue_balls = "".join([f'<div class="number-ball blue-ball">{n}</div>' for n in blue_numbers])
    
    if title == "快乐8" and red_count == 20:
        ball_container = f'<div class="ball-grid">{red_balls}</div>'
    else:
        ball_container = f'<div class="ball-container">{red_balls}{blue_balls}</div>'
    
    issue_number = str(issue) if issue else ''
    date_display = date_str if date_str else ''
    weekday_info = LOTTERY_WEEKDAYS.get(title, "")
    
    # 修正：所有信息在一行显示（左侧：彩种名称+期号+日期，右侧：开奖星期）
    header_html = f'''
<div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px;">
    <div>
        <span class="card-title" style="font-size: 1.4rem; font-weight: bold; color: #1e293b;">{title}</span>
        <span style="margin-left: 8px; font-size: 0.85rem; color: #6c757d;"> </span>
        <span style="font-size: 1.1rem; font-weight: 500; color: #1e293b;">{issue_number}</span>
        <span style="font-size: 0.85rem; color: #6c757d;"> | {date_display}</span>
    </div>
    <span style="font-size: 0.8rem; color: #6c757d;">{weekday_info}</span>
</div>
'''
    return f'<div class="lottery-card">{header_html}{ball_container}</div>'

def render_all_latest():
    st.markdown("## 🎯 最新开奖结果")
    
    # 使用北京时间
    now = get_beijing_time()
    weekdays_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday_str = weekdays_cn[now.weekday()]
    date_today_str = now.strftime("%Y年%m月%d日")
    st.markdown(f'<div style="font-size: 1.1rem; font-weight: 500; color: #1e293b; margin-bottom: 20px;">{date_today_str} {weekday_str}</div>', unsafe_allow_html=True)
    
    # 获取所有彩种最新数据
    data_map = {}
    for name, cfg in LOTTERY_CONFIG.items():
        nums, issue, date_str = get_latest_issue_data(cfg["sheet"], cfg)
        if nums:
            data_map[name] = (nums, issue, date_str, cfg)
    
    # CSS
    st.markdown("""
    <style>
    .lottery-card {
        background: #f8fafc;
        border-radius: 20px;
        padding: 16px;
        margin-bottom: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        border-left: 6px solid #4b6cb7;
        width: 100%;
    }
    .ball-container {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 8px;
    }
    .ball-grid {
        display: grid;
        grid-template-columns: repeat(10, 40px);
        gap: 6px;
        justify-content: start;
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
    @media (max-width: 768px) {
        .ball-grid {
            grid-template-columns: repeat(10, minmax(30px, 36px));
            gap: 4px;
        }
        .number-ball {
            width: 30px;
            height: 30px;
            line-height: 30px;
            font-size: 12px;
        }
        .card-title {
            font-size: 1.2rem;
        }
    }
    </style>
    """, unsafe_allow_html=True)
    
    # 按顺序显示卡片
    for name in DISPLAY_ORDER:
        if name in data_map:
            nums, issue, date_str, cfg = data_map[name]
            card_html = render_lottery_card(name, issue, date_str, nums, cfg)
            st.markdown(card_html, unsafe_allow_html=True)
    
    # 底部免责声明
    st.markdown('<div style="text-align: center; font-size: 0.9rem; color: #aaa; margin-top: 30px;">开奖信息仅供参考 最终以官方信息发布为准。</div>', unsafe_allow_html=True)

# ================== 主函数 ==================
def main():
    update_online_status()
    
    st.sidebar.title("🎰 LOTTOX 彩票")
    st.sidebar.markdown(
        f"""
        <div style="background-color:#f0f2f6; padding:6px; border-radius:8px; overflow:hidden; white-space:nowrap;">
            <div style="display:inline-block; animation: scroll-left 12s linear infinite;">
                🎯 欢迎使用LOTTOX彩票中心 | 数据每日更新 | VIP解锁高阶分析
            </div>
        </div>
        <style>
            @keyframes scroll-left {{ 0% {{ transform: translateX(100%); }} 100% {{ transform: translateX(-100%); }} }}
        </style>
        """, unsafe_allow_html=True
    )
    st.sidebar.divider()
    st.sidebar.subheader("📊 数据统计")
    st.sidebar.info("所有彩种最新一期开奖结果")
    st.sidebar.divider()
    
    if "vip_unlocked" not in st.session_state:
        st.session_state.vip_unlocked = False
        st.session_state.vip_days_left = 0
    if "show_trend" not in st.session_state:
        st.session_state.show_trend = False
    
    if not st.session_state.vip_unlocked:
        with st.sidebar.expander("🔓 VIP 解锁", expanded=False):
            auth_code = st.text_input("授权码", type="password", key="vip_code_side")
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
        st.sidebar.success(f"🌟 VIP 已激活 (剩余 {st.session_state.vip_days_left} 天)")
        selected_vip_lottery = st.sidebar.selectbox("选择彩种进行高阶分析", list(LOTTERY_CONFIG.keys()), key="vip_lottery_select")
        if st.sidebar.button("📈 走势图", use_container_width=True):
            st.session_state.show_trend = True
        if st.sidebar.button("退出 VIP", use_container_width=True):
            st.session_state.vip_unlocked = False
            st.rerun()
    
    st.sidebar.divider()
    st.sidebar.markdown(f"👥 当前在线: **{get_online_count()}**")
    
    if st.session_state.get("vip_unlocked", False) and st.session_state.get("show_trend", False):
        st.markdown("---")
        st.subheader(f"📈 {selected_vip_lottery} 走势图（开发中）")
        st.info("走势图功能即将上线，请等待后续更新。")
        st.session_state.show_trend = False
        st.markdown("---")
    
    render_all_latest()

if __name__ == "__main__":
    main()
