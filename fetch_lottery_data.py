import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import os

LOTTERIES = {
    "快乐8": {"url": "http://data.17500.cn/kl8_asc.txt", "num_cols": 20, "sheet": "kl8"},
    "双色球": {"url": "http://data.17500.cn/ssq_asc.txt", "num_cols": 7, "sheet": "ssq"},
    "大乐透": {"url": "http://data.17500.cn/dlt_asc.txt", "num_cols": 7, "sheet": "dlt"},
    "福彩3D": {"url": "https://data.17500.cn/3d_asc.txt", "num_cols": 3, "sheet": "sd"},
    "排列3": {"url": "https://data.17500.cn/pl3_asc.txt", "num_cols": 3, "sheet": "p3"},
    "排列5": {"url": "https://data.17500.cn/pl5_asc.txt", "num_cols": 5, "sheet": "p5"},
    "七星彩": {"url": "https://data.17500.cn/7xc_asc.txt", "num_cols": 7, "sheet": "qxc"},
    "七乐彩": {"url": "https://data.17500.cn/7lc_asc.txt", "num_cols": 8, "sheet": "qlc"},
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def fetch_latest_issues(name, config):
    """获取最新几期（用于增量更新），这里获取全部数据，但只取最新一期"""
    url = config['url']
    num_cols = config['num_cols']
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
        date_str = parts[1]
        numbers = []
        for n in parts[2:2+num_cols]:
            try:
                numbers.append(int(n))
            except ValueError:
                numbers.append(n)
        data_rows.append([issue, date_str] + numbers)

    # 按期号升序排列（旧在上，新在下），取最后一期（最新一期）
    if not data_rows:
        return []
    data_rows.sort(key=lambda x: int(x[0]))
    latest = data_rows[-1]   # 最新一期
    return [latest]   # 只返回最新一期用于追加

def update_google_sheet(sheet_name, latest_row):
    """将最新一期追加到 Google Sheets 工作表底部"""
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise Exception("缺少 GOOGLE_CREDS 环境变量")
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open("lotto_data")
    worksheet = spreadsheet.worksheet(sheet_name)

    # 检查最新期号是否已存在（读取第一列最后一行的值）
    last_row = worksheet.get_all_values()
    if last_row:
        last_issue = last_row[-1][0]   # 最后一行第一列
        if str(last_issue) == str(latest_row[0]):
            print(f"{sheet_name} 最新期号 {latest_row[0]} 已存在，跳过")
            return

    # 追加到末尾
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
