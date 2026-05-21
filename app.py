import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import requests
import time
import uuid
from streamlit.runtime.scriptrunner import get_script_run_ctx
from collections import Counter  # 已在分析中使用，提前导入

# ================== 页面配置 ==================
st.set_page_config(page_title="彩票历史数据中心", layout="wide")

# ================== Redis 在线人数（带前缀） ==================
APP_PREFIX = "lotto_data"  # 唯一前缀，与老站点隔离

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
    except Exception as e:
        st.sidebar.error(f"在线人数异常: {e}")

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

# ================== 显示表格 ==================
def format_numbers_row(row, number_cols):
    parts = []
    for col in number_cols:
        if col in row and pd.notna(row[col]):
            val = str(int(row[col])) if isinstance(row[col], float) else str(row[col])
            parts.append(val)
    return " ".join(parts)

def display_lottery_table(df, config):
    if df.empty:
        st.info("暂无数据")
        return
    number_cols = config["number_cols"]
    display_df = df.copy()
    display_df["开奖号码"] = display_df.apply(lambda row: format_numbers_row(row, number_cols), axis=1)
    cols_to_show = []
    if "issue" in display_df.columns:
        cols_to_show.append("期号")
        display_df.rename(columns={"issue": "期号"}, inplace=True)
    if "date" in display_df.columns:
        cols_to_show.append("日期")
        display_df["日期"] = display_df["date"].dt.strftime("%Y-%m-%d") if pd.api.types.is_datetime64_any_dtype(display_df["date"]) else display_df["date"]
        if "date" in display_df.columns:
            display_df.drop(columns=["date"], inplace=True)
    cols_to_show.append("开奖号码")
    display_df = display_df[cols_to_show]
    st.dataframe(display_df, use_container_width=True, height=600)

# ================== VIP 授权验证 ==================
def verify_card_from_sheets(user_code):
    """从 Google Sheets 的 Cards 工作表验证授权码"""
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(st.secrets["google"], scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet_id = st.secrets["google"]["spreadsheet_id"]  # 使用同一个表格，需要包含 Cards 工作表
        sh = client.open_by_key(spreadsheet_id)
        ws = sh.worksheet("Cards")
        # 使用 find 方法精确查找
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
    except Exception as e:
        return False, "验证服务异常，请稍后重试"

# ================== 彩种配置 ==================
LOTTERY_CONFIG = {
    "快乐8": {
        "sheet": "kl8",
        "columns": ["issue", "date"] + [f"n{i}" for i in range(1, 21)],
        "number_cols": [f"n{i}" for i in range(1, 21)],
    },
    "双色球": {
        "sheet": "ssq",
        "columns": ["issue", "date", "red1", "red2", "red3", "red4", "red5", "red6", "blue"],
        "number_cols": ["red1", "red2", "red3", "red4", "red5", "red6", "blue"],
    },
    "大乐透": {
        "sheet": "dlt",
        "columns": ["issue", "date", "red1", "red2", "red3", "red4", "red5", "blue1", "blue2"],
        "number_cols": ["red1", "red2", "red3", "red4", "red5", "blue1", "blue2"],
    },
    "福彩3D": {
        "sheet": "sd",
        "columns": ["issue", "date", "n1", "n2", "n3"],
        "number_cols": ["n1", "n2", "n3"],
    },
    "排列3": {
        "sheet": "p3",
        "columns": ["issue", "date", "n1", "n2", "n3"],
        "number_cols": ["n1", "n2", "n3"],
    },
    "七乐彩": {
        "sheet": "qlc",
        "columns": ["issue", "date", "n1", "n2", "n3", "n4", "n5", "n6", "n7", "special"],
        "number_cols": ["n1", "n2", "n3", "n4", "n5", "n6", "n7", "special"],
    },
    "七星彩": {
        "sheet": "qxc",
        "columns": ["issue", "date", "n1", "n2", "n3", "n4", "n5", "n6", "special"],
        "number_cols": ["n1", "n2", "n3", "n4", "n5", "n6", "special"],
    },
    "韩国乐透": {
        "sheet": "klotto",
        "columns": ["issue", "date", "n1", "n2", "n3", "n4", "n5", "n6", "special"],
        "number_cols": ["n1", "n2", "n3", "n4", "n5", "n6", "special"],
    },
}

# ================== 主界面 ==================
def main():
    # 更新在线人数（放在页面渲染前）
    update_online_status()
    
    # 侧边栏
    st.sidebar.title("🎰 彩票数据中心")
    # 滚动公告
    announcement = "🎯 欢迎使用彩票历史数据中心 | 数据每日更新 | VIP功能即将上线"
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
    
    # 彩种选择
    selected_lottery = st.sidebar.selectbox("📌 选择彩种", list(LOTTERY_CONFIG.keys()))
    config = LOTTERY_CONFIG[selected_lottery]
    
    # 数据统计
    with st.spinner(f"加载 {selected_lottery} 数据..."):
        df = load_lottery_data(config["sheet"], config["columns"])
    st.sidebar.subheader("📊 数据统计")
    if not df.empty:
        st.sidebar.metric("总期数", len(df))
        latest_issue = df["issue"].iloc[-1] if "issue" in df.columns else "N/A"
        st.sidebar.metric("最新期号", latest_issue)
    else:
        st.sidebar.info("暂无数据")
    
    # 在线人数移至侧边栏最底部（文字一行）
    st.sidebar.divider()
    st.sidebar.markdown(f"👥 当前在线: **{get_online_count()}**")
    
    # 主区域标题
    st.title(f"{selected_lottery} 历史开奖记录")
    st.caption("最新一期显示在最底部")
    
    # 显示表格
    display_lottery_table(df, config)
    
    # ========== VIP 高阶功能（解锁后显示额外分析） ==========
    st.markdown("---")
    st.subheader("🔓 VIP 高阶分析")
    
    if "vip_unlocked" not in st.session_state:
        st.session_state.vip_unlocked = False
        st.session_state.vip_days_left = 0
    
    if not st.session_state.vip_unlocked:
        # 自定义浅绿色背景提示（与 happy8 样式一致）
        st.markdown(
            """
            <div style="background-color:#d4edda; padding:10px 15px; border-radius:8px; border-left:4px solid #28a745; margin-bottom:15px;">
                🔓 该区域需解锁高阶权限，请输入授权码：
            </div>
            """,
            unsafe_allow_html=True
        )
        # 同一行布局：输入框（无标签） + 按钮
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
        # 高阶分析示例：号码频次统计（基于当前彩种数据）
        if not df.empty:
            # 统计所有号码出现次数
            all_numbers = []
            for col in config["number_cols"]:
                if col in df.columns:
                    all_numbers.extend(df[col].dropna().astype(int).tolist())
            if all_numbers:
                counter = Counter(all_numbers)
                top10 = counter.most_common(10)
                st.markdown("**🔥 历史热号 TOP 10**")
                cols = st.columns(10)
                for i, (num, cnt) in enumerate(top10):
                    cols[i].metric(num, cnt)
                st.markdown("**❄️ 历史冷号（出现次数最少）**")
                bottom10 = counter.most_common()[-10:]
                cols2 = st.columns(10)
                for i, (num, cnt) in enumerate(bottom10):
                    cols2[i].metric(num, cnt)
            else:
                st.info("无号码数据")
        else:
            st.info("暂无数据，请先选择有数据的彩种")
        
        if st.button("退出 VIP", use_container_width=True):
            st.session_state.vip_unlocked = False
            st.rerun()

if __name__ == "__main__":
    main()
