import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# ================== 页面配置 ==================
st.set_page_config(page_title="SINCOSX LOTTO 2026 彩票历史数据查询", layout="wide")

# ================== 彩种配置 ==================
LOTTERY_CONFIG = {
    "快乐8": {
        "sheet": "kl8",
        "columns": ["issue", "date"] + [f"n{i}" for i in range(1, 21)],
        "number_cols": [f"n{i}" for i in range(1, 21)],
        "date_col": "date",
        "issue_col": "issue"
    },
    "双色球": {
        "sheet": "ssq",
        "columns": ["issue", "date", "red1", "red2", "red3", "red4", "red5", "red6", "blue"],
        "number_cols": ["red1", "red2", "red3", "red4", "red5", "red6", "blue"],
        "date_col": "date",
        "issue_col": "issue"
    },
    "大乐透": {
        "sheet": "dlt",
        "columns": ["issue", "date", "red1", "red2", "red3", "red4", "red5", "blue1", "blue2"],
        "number_cols": ["red1", "red2", "red3", "red4", "red5", "blue1", "blue2"],
        "date_col": "date",
        "issue_col": "issue"
    },
    "福彩3D": {
        "sheet": "sd",
        "columns": ["issue", "date", "n1", "n2", "n3"],
        "number_cols": ["n1", "n2", "n3"],
        "date_col": "date",
        "issue_col": "issue"
    },
    "排列3": {
        "sheet": "p3",
        "columns": ["issue", "date", "n1", "n2", "n3"],
        "number_cols": ["n1", "n2", "n3"],
        "date_col": "date",
        "issue_col": "issue"
    },
    "七乐彩": {
        "sheet": "qlc",
        "columns": ["issue", "date", "n1", "n2", "n3", "n4", "n5", "n6", "n7", "special"],
        "number_cols": ["n1", "n2", "n3", "n4", "n5", "n6", "n7", "special"],
        "date_col": "date",
        "issue_col": "issue"
    },
    "七星彩": {
        "sheet": "qxc",
        "columns": ["issue", "date", "n1", "n2", "n3", "n4", "n5", "n6", "special"],
        "number_cols": ["n1", "n2", "n3", "n4", "n5", "n6", "special"],
        "date_col": "date",
        "issue_col": "issue"
    },
    "韩国乐透": {
        "sheet": "klotto",
        "columns": ["issue", "date", "n1", "n2", "n3", "n4", "n5", "n6", "special"],
        "number_cols": ["n1", "n2", "n3", "n4", "n5", "n6", "special"],
        "date_col": "date",
        "issue_col": "issue"
    }
}

# ================== Google Sheets 连接 ==================
@st.cache_resource
def get_gsheet_client():
    """获取 Google Sheets 客户端（单例）"""
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["google"], scopes=scopes)
    return gspread.authorize(creds)

@st.cache_data(ttl=3600)  # 缓存1小时
def load_lottery_data(sheet_name, expected_columns):
    """从指定工作表加载数据，返回 DataFrame（期号升序）"""
    try:
        client = get_gsheet_client()
        # 打开表格（根据你的实际表格名称修改）
        spreadsheet = client.open("lotto_data")  # 注意：这里是你的表格名称，不是文件名
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # 获取所有数据（从A1开始）
        all_data = worksheet.get_all_values()
        if len(all_data) < 2:
            return pd.DataFrame(columns=expected_columns)
        
        # 第一行作为表头
        headers = all_data[0]
        rows = all_data[1:]
        
        # 将数据转换为 DataFrame
        df = pd.DataFrame(rows, columns=headers)
        
        # 只保留需要的列（如果实际列名与预期不完全一致，进行映射）
        # 由于你的表格列名与 expected_columns 基本一致，我们直接取交集
        existing_cols = [col for col in expected_columns if col in df.columns]
        df = df[existing_cols]
        
        # 转换期号为数值（用于排序）
        if "issue" in df.columns:
            df["issue"] = pd.to_numeric(df["issue"], errors="coerce")
            df = df.dropna(subset=["issue"])
            df = df.sort_values("issue", ascending=True)  # 升序，最新一期在底部
        
        # 转换日期（可选）
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        
        return df
    except Exception as e:
        st.error(f"加载 {sheet_name} 数据失败: {str(e)}")
        return pd.DataFrame()

# ================== 显示表格 ==================
def format_numbers_row(row, number_cols):
    """将号码列格式化为字符串，方便显示"""
    parts = []
    for col in number_cols:
        if col in row and pd.notna(row[col]):
            val = str(int(row[col])) if isinstance(row[col], float) else str(row[col])
            # 对于双色球、大乐透等，蓝球可以单独标记，这里简单拼接
            parts.append(val)
    return " ".join(parts)

def display_lottery_table(df, config):
    """显示彩票数据表格，最新一期在底部"""
    if df.empty:
        st.info("暂无数据")
        return
    
    number_cols = config["number_cols"]
    # 构建展示用的 DataFrame
    display_df = df.copy()
    # 添加“开奖号码”列（合并所有号码）
    display_df["开奖号码"] = display_df.apply(lambda row: format_numbers_row(row, number_cols), axis=1)
    
    # 选择要显示的列（期号、日期、开奖号码）
    cols_to_show = []
    if "issue" in display_df.columns:
        cols_to_show.append("期号")
        display_df.rename(columns={"issue": "期号"}, inplace=True)
    if "date" in display_df.columns:
        cols_to_show.append("日期")
        display_df.rename(columns={"date": "日期"}, inplace=True)
    cols_to_show.append("开奖号码")
    
    # 如果原始数据中有特殊号码列（如蓝球），也可以单独展示，但合并列已包含
    st.dataframe(display_df[cols_to_show], use_container_width=True, height=600)

# ================== 主界面 ==================
def main():
    st.title("📊 彩票历史数据中心")
    
    # 侧边栏选择彩种
    st.sidebar.title("彩种选择")
    selected_lottery = st.sidebar.selectbox("请选择彩种", list(LOTTERY_CONFIG.keys()))
    
    # 获取配置
    config = LOTTERY_CONFIG[selected_lottery]
    sheet_name = config["sheet"]
    
    # 加载数据
    with st.spinner(f"正在加载 {selected_lottery} 数据..."):
        df = load_lottery_data(sheet_name, config["columns"])
    
    # 显示数据统计
    st.sidebar.markdown("---")
    st.sidebar.subheader("数据统计")
    if not df.empty:
        st.sidebar.metric("总期数", len(df))
        latest_issue = df["issue"].max() if "issue" in df.columns else "N/A"
        st.sidebar.metric("最新期号", latest_issue)
    else:
        st.sidebar.info("暂无数据")
    
    # 右侧显示数据表格
    st.subheader(f"{selected_lottery} 历史开奖记录 (最新一期在底部)")
    display_lottery_table(df, config)
    
    # 可选：显示原始数据前几行（调试用）
    with st.expander("查看原始数据（前5行）"):
        st.dataframe(df.head(5))

if __name__ == "__main__":
    main()
