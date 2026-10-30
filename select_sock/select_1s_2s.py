import os
import time
import random
from typing import Dict, List, Optional

import pandas as pd
import requests


# ============================================================
# 配置
# ============================================================

DISABLE_PROXY = True

SINA_URL = "https://hq.sinajs.cn/list={symbols}"

# 每批查询多少个代码
# 新浪支持多代码查询，但不要太大，建议 80~200
BATCH_SIZE = 120

# 请求间隔，防止被限制
MIN_INTERVAL = 1.2
JITTER_MIN = 0.3
JITTER_MAX = 1.0

OUTPUT_CSV = "a_share_main_board_2000_3000_candidates_sina.csv"
OUTPUT_TXT = "a_share_main_board_2000_3000_codes_sina.txt"


# ============================================================
# 网络
# ============================================================

def clear_proxy_env() -> None:
    proxy_keys = [
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ]
    for key in proxy_keys:
        os.environ.pop(key, None)


def build_session() -> requests.Session:
    if DISABLE_PROXY:
        clear_proxy_env()

    session = requests.Session()
    session.trust_env = False

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://finance.sina.com.cn/",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })

    return session


SESSION = build_session()
LAST_REQUEST_TIME = 0.0


def rate_limit_wait() -> None:
    global LAST_REQUEST_TIME

    now = time.time()
    interval = MIN_INTERVAL + random.uniform(JITTER_MIN, JITTER_MAX)
    elapsed = now - LAST_REQUEST_TIME

    if elapsed < interval:
        time.sleep(interval - elapsed)

    LAST_REQUEST_TIME = time.time()


def sina_get(symbols: List[str], max_retries: int = 5) -> str:
    """
    请求新浪行情。
    symbols 示例：
    ["sh600519", "sz000001"]
    """
    url = SINA_URL.format(symbols=",".join(symbols))

    last_error = None

    for retry in range(max_retries):
        try:
            rate_limit_wait()

            response = SESSION.get(
                url,
                timeout=15,
                proxies={} if DISABLE_PROXY else None,
            )

            response.raise_for_status()

            # 新浪行情常见编码是 GBK/GB2312
            response.encoding = "gbk"

            if not response.text.strip():
                wait_seconds = 5 * (retry + 1)
                print(f"新浪返回空内容，等待 {wait_seconds} 秒后重试")
                time.sleep(wait_seconds)
                continue

            return response.text

        except Exception as e:
            last_error = e
            wait_seconds = 5 * (retry + 1) + random.uniform(1, 5)
            print(
                f"新浪请求失败，第 {retry + 1}/{max_retries} 次："
                f"{repr(e)}，等待 {wait_seconds:.1f} 秒后重试"
            )
            time.sleep(wait_seconds)

    raise RuntimeError(f"新浪请求失败，最后错误：{last_error}")


# ============================================================
# 代码生成
# ============================================================

def generate_main_board_symbols() -> Dict[str, str]:
    """
    生成主板普通A股可能代码。

    返回：
    {
        "sh600000": "600000",
        "sz000001": "000001",
        ...
    }
    """
    code_map: Dict[str, str] = {}

    prefixes = [
        "600", "601", "603", "605",
        "000", "001", "002", "003",
    ]

    for prefix in prefixes:
        for i in range(1000):
            code = f"{prefix}{i:03d}"

            if code.startswith(("600", "601", "603", "605")):
                symbol = f"sh{code}"
            else:
                symbol = f"sz{code}"

            code_map[symbol] = code

    return code_map


def chunk_list(items: List[str], batch_size: int) -> List[List[str]]:
    return [
        items[i:i + batch_size]
        for i in range(0, len(items), batch_size)
    ]


# ============================================================
# 新浪返回解析
# ============================================================

def parse_sina_line(line: str) -> Optional[Dict[str, object]]:
    """
    新浪返回示例：
    var hq_str_sh600519="贵州茅台,1420.00,1410.00,1415.00,...,2026-xx-xx,15:00:00,...";

    常用字段：
    0  名称
    1  开盘价
    2  昨收价
    3  当前价
    4  最高价
    5  最低价
    8  成交量
    9  成交额
    30 日期
    31 时间
    """
    line = line.strip()

    if not line or "var hq_str_" not in line:
        return None

    try:
        left, right = line.split("=", 1)
        symbol = left.replace("var hq_str_", "").strip()
        raw = right.strip().strip(";").strip('"')
    except ValueError:
        return None

    # 无效代码通常为空字符串
    if not raw:
        return None

    parts = raw.split(",")

    if len(parts) < 4:
        return None

    name = parts[0].strip()

    # 无效股票、未上市、退市等经常名称为空或价格为0
    if not name:
        return None

    try:
        open_price = float(parts[1])
        pre_close = float(parts[2])
        price = float(parts[3])
        high = float(parts[4]) if len(parts) > 4 and parts[4] else None
        low = float(parts[5]) if len(parts) > 5 and parts[5] else None
    except Exception:
        return None

    # 当前价为0，通常是无效、停牌或异常，这里先排除
    if price <= 0:
        return None

    code = symbol[-6:]

    pct_chg = None
    if pre_close > 0:
        pct_chg = (price - pre_close) / pre_close * 100

    trade_date = parts[30] if len(parts) > 30 else ""
    trade_time = parts[31] if len(parts) > 31 else ""

    return {
        "code": code,
        "symbol": symbol,
        "name": name,
        "price": price,
        "pre_close": pre_close,
        "open": open_price,
        "high": high,
        "low": low,
        "pct_chg": pct_chg,
        "trade_date": trade_date,
        "trade_time": trade_time,
    }


def parse_sina_response(text: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []

    for line in text.splitlines():
        item = parse_sina_line(line)
        if item:
            rows.append(item)

    return rows


# ============================================================
# 获取行情
# ============================================================

def fetch_sina_main_board_spot() -> pd.DataFrame:
    code_map = generate_main_board_symbols()
    symbols = list(code_map.keys())
    batches = chunk_list(symbols, BATCH_SIZE)

    all_rows: List[Dict[str, object]] = []

    print(f"准备查询主板候选代码数量：{len(symbols)}")
    print(f"批次数量：{len(batches)}，每批最多 {BATCH_SIZE} 个")

    for idx, batch in enumerate(batches, start=1):
        text = sina_get(batch)
        rows = parse_sina_response(text)
        all_rows.extend(rows)

        print(
            f"已请求第 {idx}/{len(batches)} 批，"
            f"本批有效 {len(rows)} 条，累计有效 {len(all_rows)} 条"
        )

    df = pd.DataFrame(all_rows)

    if df.empty:
        return pd.DataFrame(columns=[
            "code", "symbol", "name", "price", "pct_chg",
            "trade_date", "trade_time",
        ])

    df["code"] = df["code"].astype(str).str.zfill(6)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")

    df = df.dropna(subset=["price"])

    return df


# ============================================================
# 筛选逻辑
# ============================================================

def is_main_board_common_a(code: str, name: str) -> bool:
    code = str(code).zfill(6)
    name = str(name)
    upper_name = name.upper()

    is_main_board = code.startswith((
        "600", "601", "603", "605",
        "000", "001", "002", "003",
    ))

    is_risky_name = (
        "ST" in upper_name
        or "*ST" in upper_name
        or "退" in name
        or "退市" in name
    )

    return is_main_board and not is_risky_name


def filter_candidates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df = df[df.apply(
        lambda row: is_main_board_common_a(row["code"], row["name"]),
        axis=1,
    )]

    # 1手=100股，2000-3000元，对应价格20-30元
    buy_1_lot = df[
        (df["price"] >= 20)
        & (df["price"] <= 30)
    ].copy()

    buy_1_lot["buy_type"] = "1手"
    buy_1_lot["shares"] = 100
    buy_1_lot["estimated_amount"] = buy_1_lot["price"] * 100

    # 2手=200股，2000-3000元，对应价格10-15元
    buy_2_lot = df[
        (df["price"] >= 10)
        & (df["price"] <= 15)
    ].copy()

    buy_2_lot["buy_type"] = "2手"
    buy_2_lot["shares"] = 200
    buy_2_lot["estimated_amount"] = buy_2_lot["price"] * 200

    result = pd.concat([buy_1_lot, buy_2_lot], ignore_index=True)

    if result.empty:
        return result

    keep_cols = [
        "buy_type",
        "code",
        "symbol",
        "name",
        "price",
        "shares",
        "estimated_amount",
        "pct_chg",
        "trade_date",
        "trade_time",
    ]

    for col in keep_cols:
        if col not in result.columns:
            result[col] = None

    result = result[keep_cols]

    result = result.sort_values(
        by=["buy_type", "price", "code"],
        ascending=[True, True, True],
    )

    return result


# ============================================================
# 输出
# ============================================================

def save_results(result: pd.DataFrame) -> None:
    result.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    buy_1_lot_codes = (
        result[result["buy_type"] == "1手"]["code"]
        .sort_values()
        .tolist()
    )

    buy_2_lot_codes = (
        result[result["buy_type"] == "2手"]["code"]
        .sort_values()
        .tolist()
    )

    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write("买1手约2000-3000元的股票代码：\n")
        f.write(",".join(buy_1_lot_codes))
        f.write("\n\n")
        f.write("买2手约2000-3000元的股票代码：\n")
        f.write(",".join(buy_2_lot_codes))
        f.write("\n")

    print("\n========== 买1手约2000-3000元的股票代码 ==========")
    print(",".join(buy_1_lot_codes))

    print("\n========== 买2手约2000-3000元的股票代码 ==========")
    print(",".join(buy_2_lot_codes))

    print(f"\n已保存详细结果：{OUTPUT_CSV}")
    print(f"已保存代码列表：{OUTPUT_TXT}")


def main() -> None:
    print("开始从新浪获取A股行情，不走东方财富...")

    df = fetch_sina_main_board_spot()

    print(f"\n新浪行情获取完成，有效股票数量：{len(df)}")
    print("开始筛选主板普通股票中，2000-3000元可以买1手或2手的股票...")

    result = filter_candidates(df)

    if result.empty:
        print("\n没有筛选到符合条件的股票。")
        return

    print(f"\n筛选完成，共 {len(result)} 条结果。")

    save_results(result)


if __name__ == "__main__":
    main()