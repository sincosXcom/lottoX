import requests
import gspread
from google.oauth2.service_account import Credentials
import os
import json
import re

# ================== 快乐8 ==================
def fetch_kl8():
    url = "http://data.17500.cn/kl8_asc.txt"
    resp = requests.get(url, timeout=10)
    resp.encoding = "utf-8"
    lines = resp.text.splitlines()
    result = []
    # 快乐8: 格式: 期号 日期 20个号码 ...
    for line in lines:
        line = line.strip()
        if not line or "URL:" in line:
            continue
        parts = line.split()
        if len(parts) < 22:  # 期号 + 日期 + 至少20个号码
            continue
        issue = parts[0]
        date = parts[1]
        numbers = parts[2:22]  # 取前20个号码
        result.append([issue, date] + numbers)
    return result

# ================== 双色球 ==================
def fetch_ssq():
    url = "http://data.17500.cn/ssq_asc.txt"
    resp = requests.get(url, timeout=10)
    resp.encoding = "utf-8"
    lines = resp.text.splitlines()
    result = []
    # 双色球: 格式: 期号 日期 6个红球 1个蓝球 后面是冗余数据
    for line in lines:
        line = line.strip()
        if not line or "URL:" in line:
            continue
        parts = line.split()
        if len(parts) < 8:
            continue
        issue = parts[0]
        date = parts[1]
        reds = parts[2:8]    # 6个红球
        blue = parts[8:9]    # 1个蓝球
        numbers = reds + blue
        result.append([issue, date] + numbers)
    return result

# ================== 大乐透 ==================
def fetch_dlt():
    url = "http://data.17500.cn/dlt_asc.txt"
    resp = requests.get(url, timeout=10)
    resp.encoding = "utf-8"
    lines = resp.text.splitlines()
    result = []
    # 大乐透: 格式: 期号 日期 5个前区 2个后区
    for line in lines:
        line = line.strip()
        if not line or "URL:" in line:
            continue
        parts = line.split()
        if len(parts) < 9:
            continue
        issue = parts[0]
        date = parts[1]
        reds = parts[2:7]    # 5个前区
        blues = parts[7:9]   # 2个后区
        numbers = reds + blues
        result.append([issue, date] + numbers)
    return result

# ================== 福彩3D ==================
def fetch_3d():
    url = "https://data.17500.cn/3d_asc.txt"
    resp = requests.get(url, timeout=10)
    resp.encoding = "utf-8"
    lines = resp.text.splitlines()
    result = []
    # 3D: 格式: 期号 日期 3个号码 ... (后面有冗余数据，取前3个)
    for line in lines:
        line = line.strip()
        if not line or "URL:" in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        issue = parts[0]
        date = parts[1]
        numbers = parts[2:5]   # 前3个数字
        result.append([issue, date] + numbers)
    return result

# ================== 排列3 ==================
def fetch_pl3():
    url = "https://data.17500.cn/pl3_asc.txt"
    resp = requests.get(url, timeout=10)
    resp.encoding = "utf-8"
    lines = resp.text.splitlines()
    result = []
    # 排列3: 格式: 期号 日期 3个号码 ... (后面有销售数据，取前3个)
    for line in lines:
        line = line.strip()
        if not line or "URL:" in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        issue = parts[0]
        date = parts[1]
        numbers = parts[2:5]
        result.append([issue, date] + numbers)
    return result

# ================== 排列5 ==================
def fetch_pl5():
    url = "https://data.17500.cn/pl5_asc.txt"
    resp = requests.get(url, timeout=10)
    resp.encoding = "utf-8"
    lines = resp.text.splitlines()
    result = []
    # 排列5: 格式: 期号 日期 5个号码 ... (后面是销售数据，取前5个)
    for line in lines:
        line = line.strip()
        if not line or "URL:" in line:
            continue
        parts = line.split()
        if len(parts) < 7:
            continue
        issue = parts[0]
        date = parts[1]
        numbers = parts[2:7]
        result.append([issue, date] + numbers)
    return result

# ================== 七星彩 ==================
def fetch_qxc():
    url = "https://data.17500.cn/7xc_asc.txt"
    resp = requests.get(url, timeout=10)
    resp.encoding = "utf-8"
    lines = resp.text.splitlines()
    result = []
    # 七星彩: 格式: 期号 日期 7个号码 ... (后面是销售数据)
    for line in lines:
        line = line.strip()
        if not line or "URL:" in line:
            continue
        parts = line.split()
        if len(parts) < 9:
            continue
        issue = parts[0]
        date = parts[1]
        numbers = parts[2:9]
        result.append([issue, date] + numbers)
    return result

# ================== 七乐彩 ==================
def fetch_7lc():
    url = "https://data.17500.cn/7lc_asc.txt"
    resp = requests.get(url, timeout=10)
    resp.encoding = "utf-8"
    lines = resp.text.splitlines()
    result = []
    # 七乐彩: 格式: 期号 日期 7个基本号码 + 1个特别号
    for line in lines:
        line = line.strip()
        if not line or "URL:" in line:
            continue
        parts = line.split()
        if len(parts) < 10:
            continue
        issue = parts[0]
        date = parts[1]
        numbers = parts[2:10]   # 7个基本 + 1个特别
        result.append([issue, date] + numbers)
    return result

# ================== 更新 Google Sheets ==================
def update_sheet(sheet_name, data_rows):
    """更新指定工作表，追加新数据"""
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise Exception("缺少 GOOGLE_CREDS 环境变量")
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    spreadsheet = client.open("lotto_data")
    sheet = spreadsheet.worksheet(sheet_name)

    # 获取已有期号（第一列）
    existing_records = sheet.get_all_values()
    existing_issues = set()
    for row in existing_records:
        if row:
            existing_issues.add(row[0])

    # 过滤出需要追加的新数据
    new_rows = []
    for row in data_rows:
        issue = row[0]
        if issue not in existing_issues:
            new_rows.append(row)
        else:
            print(f"期号 {issue} 已存在，跳过")

    if new_rows:
        # 批量追加行
        for row in new_rows:
            sheet.append_row(row)
        print(f"成功更新 {sheet_name}，新增 {len(new_rows)} 期数据")
    else:
        print(f"{sheet_name} 无新数据")

def main():
    # 定义所有彩种及其对应的工作表名和抓取函数
    lotteries = [
        ("kl8", fetch_kl8),
        ("ssq", fetch_ssq),
        ("dlt", fetch_dlt),
        ("sd", fetch_3d),
        ("pl3", fetch_pl3),
        ("pl5", fetch_pl5),
        ("qxc", fetch_qxc),
        ("qlc", fetch_7lc),   # 七乐彩工作表名为 qlc
    ]

    for sheet_name, fetch_func in lotteries:
        print(f"正在抓取 {sheet_name} 数据...")
        try:
            data_rows = fetch_func()
            if data_rows:
                update_sheet(sheet_name, data_rows)
            else:
                print(f"{sheet_name} 抓取失败或无数据")
        except Exception as e:
            print(f"处理 {sheet_name} 时发生错误: {e}")

if __name__ == '__main__':
    main()
