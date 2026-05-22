import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import os

# 彩种配置：增加 convert_issue 标志
LOTTERIES = {
    "快乐8": {"url": "http://data.17500.cn/kl8_asc.txt", "num_cols": 20, "sheet": "kl8", "convert_issue": False},
    "双色球": {"url": "http://data.17500.cn/ssq_asc.txt", "num_cols": 7, "sheet": "ssq", "convert_issue": False},
    "大乐透": {"url": "http://data.17500.cn/dlt_asc.txt", "num_cols": 7, "sheet": "dlt", "convert_issue": False},
    "福彩3D": {"url": "https://data.17500.cn/3d_asc.txt", "num_cols": 3, "sheet": "sd", "convert_issue": False},
    "排列3": {"url": "https://data.17500.cn/pl3_asc.txt", "num_cols": 3, "sheet": "p3", "convert_issue": True},
    "排列5": {"url": "https://data.17500.cn/pl5_asc.txt", "num_cols": 5, "sheet": "p5", "convert_issue": True},
    "七星彩": {"url": "https://data.17500.cn/7xc_asc.txt", "num_cols": 7, "sheet": "qxc", "convert_issue": False},
    "七乐彩": {"url": "https://data.17500.cn/7lc_asc.txt", "num_cols": 8, "sheet": "qlc", "convert_issue": False},
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def fetch_latest_issues(name, config):
    """获取最新一期数据（期号已转换）"""
    url = config['url']
    num_cols = config['num_cols']
    convert = config.get('convert_issue', False)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'utf-8'
        if resp.status_code != 200:
            print(f"{name} HTTP {resp.status_code}")
            return []
        lines = resp.text.splitlines()
    except Exception as e:
        print(f"{name} 请求异常: {e}")
        return []

    data_rows = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("URL:") or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2 + num_cols:
            continue
        issue = parts[0]
        if convert:
            issue = issue[2:]   # 去掉前两位 "20"，例如 2026131 → 26131
        date_str = parts[1]
        numbers = []
        for n in parts[2:2+num_cols]:
            try:
                numbers.append(int(n))
            except ValueError:
                numbers.append(n)
        data_rows.append([issue, date_str] + numbers)

    if not data_rows:
        return []
    # 按期号数值升序排序，取最后一期（最新）
    data_rows.sort(key=lambda x: int(x[0]))
    latest = data_rows[-1]
    return [latest]

def update_google_sheet(sheet_name, latest_row):
    """将最新一期追加到工作表底部（去重）"""
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise Exception("缺少 GOOGLE_CREDS 环境变量")
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open("lotto_data")
    worksheet = spreadsheet.worksheet(sheet_name)

    # 获取最后一行的期号
    last_row_vals = worksheet.get_all_values()
    if last_row_vals:
        last_issue = last_row_vals[-1][0]
        if str(last_issue) == str(latest_row[0]):
            print(f"{sheet_name} 最新期号 {latest_row[0]} 已存在，跳过")
            return

    worksheet.append_row(latest_row)
    print(f"{sheet_name} 已追加最新期号 {latest_row[0]}")

def main():
    for name, config in LOTTERIES.items():
        print(f"处理 {name}...")
        latest_rows = fetch_latest_issues(name, config)
        if latest_rows:
            update_google_sheet(config["sheet"], latest_rows[0])
        else:
            print(f"  {name} 未获取到最新数据")

if __name__ == "__main__":
    main()
