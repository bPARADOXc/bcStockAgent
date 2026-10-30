import os
import requests

for key in [
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
    "all_proxy", "ALL_PROXY"
]:
    os.environ.pop(key, None)

s = requests.Session()
s.trust_env = False

tests = [
    "http://www.baidu.com",
    "https://www.baidu.com",
    "http://push2.eastmoney.com",
    "https://push2.eastmoney.com",
]

for url in tests:
    print("\n测试：", url)
    try:
        r = s.get(url, timeout=10, proxies={})
        print("状态码：", r.status_code)
        print("前100字符：", r.text[:100])
    except Exception as e:
        print("失败：", repr(e))