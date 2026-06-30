#!/usr/bin/env python3
"""诊断脚本：调用后端查 project 状态 / activate 响应。"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:9022"


def request(method, path, token=None, body=None):
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def login():
    data = urllib.parse.urlencode({"username": "admin", "password": "admin123"}).encode()
    req = urllib.request.Request(
        BASE + "/api/auth/login",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)["access_token"]


def main():
    t = login()
    print("[ok] login")
    code, body = request("GET", "/api/projects", t)
    print("[GET projects]", code)
    projs = json.loads(body) if code == 200 else []
    print("  count=%d slugs=%s" % (len(projs), [p["slug"] for p in projs]))
    e2e = [p for p in projs if p["slug"] == "e2e"]
    if not e2e:
        print("no e2e project")
        sys.exit(0)
    pid = e2e[0]["id"]
    code, body = request("POST", "/api/projects/" + pid + "/activate", t)
    print("[activate]", code)
    print(body[:800])


if __name__ == "__main__":
    main()
