import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import requests
import time
import uuid
from streamlit.runtime.scriptrunner import get_script_run_ctx
# 导入 collections 用于统计
from collections import Counter

# ================== 1. 页面配置 ==================
st.set_page_config(page_title="彩票数据中心 | 高阶矩阵", layout="wide")

# ================== 2. 侧边栏 UI 组件 ==================
def render_sidebar():
    with st.sidebar:
        st.title("🎰 彩票数据中心")
        
        # 滚动公告
        announcement = "🎯 欢迎使用彩票数据中心 | 数据每日更新 | 解锁VIP体验高阶预测"
        st.markdown(
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
        st.divider()
        
        # 在线人数显示（此处仅调用显示函数，状态更新在 main 入口执行）
        st.metric("👥 当前在线", get_online_count())
        st.divider()
        
        # 彩种选择
        selected_lottery = st.selectbox("📌 选择彩种", list(LOTTERY_CONFIG.keys()))
        st.divider()
        
        # 数据统计
        st.subheader("📊 数据统计")
        # 数据统计内容将在主循环中更新，此处预留位置
        return selected_lottery

# 注意：您原有的或新的 Redis 键名前缀
APP_PREFIX = "lotto_data"

class RedisClient:
    # ... (您原有的 RedisClient 类保持不变) ...
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
        # 静默失败，避免影响主流程
        pass

def get_online_count():
    try:
        r = get_redis()
        return r.scard("online_users_set")
    except:
        return 0

# ================== 3. Google Sheets 数据加载与授权验证 ==================
@st.cache_resource
def get_gsheet_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(st.secrets["google"], scopes=scopes)
    return gspread.authorize(creds)

@st.cache_data(ttl=3600)
def load_lottery_data(sheet_name, expected_columns):
    # ... (您原有的数据加载函数保持不变) ...
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

def verify_card_from_sheets(user_code):
    """安全验证卡密，不泄露任何数据"""
    # ... (您提供的验证函数保持不变) ...
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

        code = row_data[0].strip()
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
            used = (now - start).days
            remaining = int(days_str) - used
            if remaining > 0:
                return True, remaining
            else:
                return False, f"授权已过期 {remaining} 天"
    except Exception:
        return False, "验证服务异常，请稍后重试"

def load_tomorrow_data():
    """从 Google Sheets 的 'tomorrow' 工作表加载并解析高阶预测数据。"""
    # ... (您原有的数据加载与解析逻辑保持不变，并返回 groups_by_temp 和 common_issue) ...
    # 这里假设您的解析逻辑已经实现，并返回 groups_by_temp (dict) 和 common_issue (str)
    # 为了示例，这里返回模拟数据，您需要替换为真实的解析逻辑
    # groups_by_temp = {
    #     "1.0": [{"title": "LSTM - Table", "numbers": ["01","02",...]}, ...],
    #     "1.5": [...],
    #     "2.0": [...]
    # }
    # common_issue = "2026131"
    # 请替换为您的实际解析逻辑
    groups_by_temp = {}
    common_issue = None
    try:
        client = get_gsheet_client()
        spreadsheet_id = st.secrets["google"]["spreadsheet_id"]
        sh = client.open_by_key(spreadsheet_id)
        ws = sh.worksheet("tomorrow")
        # 解析逻辑...
        # ...
        # 示例：返回空数据，表示未实现
        st.warning("'tomorrow' 工作表解析逻辑待实现，请参考之前的代码进行替换。")
    except Exception as e:
        st.error(f"加载高阶预测数据失败: {e}")
    return groups_by_temp, common_issue


# ================== 4. 辅助函数 ==================
def display_lottery_table(df, config):
    # ... (您原有的表格展示函数保持不变) ...
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

def format_numbers_row(row, number_cols):
    # ... (您原有的格式化函数保持不变) ...
    parts = []
    for col in number_cols:
        if col in row and pd.notna(row[col]):
            val = str(int(row[col])) if isinstance(row[col], float) else str(row[col])
            parts.append(val)
    return " ".join(parts)


# ================== 5. 高阶矩阵预测显示模块 ==================
def display_prediction_card(title, numbers):
    """使用 HTML/CSS 生成并显示一个漂亮的预测卡片"""
    numbers_html = "".join([f'<div class="number-block">{num}</div>' for num in numbers])
    card_html = f"""
    <div class="group-card">
        <div class="group-title">🎯 {title}</div>
        <div class="numbers-container">
            {numbers_html}
        </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)
    return f"{title}: " + " ".join(numbers)

def display_advanced_predictions(groups_by_temp, temp_order):
    """按温度分组展示预测结果，并生成所有号码文本用于一键复制。"""
    all_lines = []
    st.markdown("""
    <style>
    .number-block {
        display: inline-block;
        background: linear-gradient(135deg, #4b6cb7, #182848);
        color: white;
        border-radius: 50%;
        width: 40px;
        height: 40px;
        line-height: 40px;
        text-align: center;
        margin: 4px;
        font-weight: bold;
        font-size: 15px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }
    .group-card {
        background: #f8fafc;
        border-radius: 16px;
        padding: 12px 16px;
        margin-bottom: 24px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        border-left: 6px solid #4b6cb7;
    }
    .group-title {
        font-size: 1.2rem;
        font-weight: bold;
        color: #1e293b;
        margin-bottom: 12px;
        border-bottom: 1px solid #e2e8f0;
        padding-bottom: 6px;
    }
    .numbers-container {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
        margin-top: 8px;
    }
    .temp-section {
        margin-bottom: 32px;
    }
    .temp-header {
        font-size: 1.4rem;
        font-weight: bold;
        color: #0f172a;
        background: #eef2ff;
        padding: 8px 16px;
        border-radius: 28px;
        display: inline-block;
        margin-bottom: 20px;
    }
    </style>
    """, unsafe_allow_html=True)

    for temp_val in temp_order:
        if temp_val not in groups_by_temp:
            continue
        st.markdown(f'<div class="temp-section"><div class="temp-header">🌡️ 温度 {temp_val}</div></div>', unsafe_allow_html=True)
        for g in groups_by_temp[temp_val]:
            line = display_prediction_card(g['title'], g['numbers'])
            all_lines.append(line)

    if all_lines:
        full_text = "\n\n".join(all_lines)
        st.text_area("📋 全部 18 组号码（可选中复制）", full_text, height=200)


# ================== 6. 主应用 ==================
def main():
    # 初始化 session state
    if "vip_unlocked" not in st.session_state:
        st.session_state.vip_unlocked = False
        st.session_state.vip_days_left = 0

    # 页面加载时更新在线状态
    update_online_status()

    # 侧边栏渲染（在线人数组件需要在 update_online_status 之后渲染以获取最新数据）
    with st.sidebar:
        st.title("🎰 彩票数据中心")
        # 滚动公告
        announcement = "🎯 欢迎使用彩票数据中心 | 数据每日更新 | 解锁VIP体验高阶预测"
        st.markdown(
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
        st.divider()
        
        # 侧边栏底部显示在线人数
        st.metric("👥 当前在线", get_online_count())
        st.divider()
        
        # 彩种选择
        selected_lottery = st.selectbox("📌 选择彩种", list(LOTTERY_CONFIG.keys()))
        st.divider()
        
        # 数据统计占位（实际数据在主区域加载后更新）
        stats_placeholder = st.empty()

    # 主区域：历史数据展示
    config = LOTTERY_CONFIG[selected_lottery]
    with st.spinner(f"加载 {selected_lottery} 数据..."):
        df = load_lottery_data(config["sheet"], config["columns"])
    
    if not df.empty:
        stats_placeholder.metric("总期数", len(df))
        stats_placeholder.metric("最新期号", df["issue"].iloc[-1] if "issue" in df.columns else "N/A")
    else:
        stats_placeholder.info("暂无数据")

    st.title(f"{selected_lottery} 历史开奖记录")
    st.caption("最新一期显示在最底部")
    display_lottery_table(df, config)
    
    # 高阶矩阵预测区域
    st.markdown("---")
    st.subheader("🔓 VIP 高阶矩阵预测")
    
    if not st.session_state.vip_unlocked:
        # 解锁界面
        col1, col2 = st.columns([2, 1])
        with col1:
            auth_code = st.text_input("请输入授权码", type="password", key="vip_code")
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
        # 加载并展示高阶预测数据
        groups_by_temp, common_issue = load_tomorrow_data()
        if groups_by_temp and common_issue:
            st.markdown(f"**📅 预测期号：{common_issue}**")
            display_advanced_predictions(groups_by_temp, ["2.0", "1.0", "1.5"])  # 注意温度顺序
        else:
            st.info("今日暂无高阶预测数据，请联系管理员。")
        
        if st.button("退出 VIP", use_container_width=True):
            st.session_state.vip_unlocked = False
            st.rerun()

if __name__ == "__main__":
    # 彩种配置（在 main 外部定义，确保在调用前存在）
    LOTTERY_CONFIG = {
        "快乐8": {
            "sheet": "kl8",
            "columns": ["issue", "date"] + [f"n{i}" for i in range(1, 21)],
            "number_cols": [f"n{i}" for i in range(1, 21)],
        },
        # ... 其他彩种配置 ...
    }
    main()
