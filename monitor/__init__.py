"""xhs-monitor 包初始化：绕过系统代理直连小红书。

系统常驻代理（如 Clash 7890）会拦截 TLS 导致证书错误，且境外出口节点
易触发平台风控；小红书为国内站点，直连即可。
"""
import os

for _k in ("http_proxy", "https_proxy", "all_proxy",
           "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_k, None)
