import argparse
import json
import re
from pathlib import Path


def read_issue(issue, owner):
    user = issue.get("user") or {}
    if issue.get("pull_request") or user.get("login", "").casefold() != owner.casefold():
        raise ValueError("Chỉ Issue do chủ repo mở mới được nhận.")
    title = issue.get("title") or ""
    if not title.casefold().startswith("[40k]") or not title[5:].strip():
        raise ValueError("Tiêu đề cần có dạng [40K] Tên video.")
    script = re.sub(r"<!--.*?-->", "", issue.get("body") or "", flags=re.DOTALL).strip()
    if not script:
        raise ValueError("Issue chưa có lời thoại.")
    return title[5:].strip(), script


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--script", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = json.loads(args.issue.read_text(encoding="utf-8"))
        title, script = read_issue(data.get("issue", data), args.owner)
        args.script.write_text(script + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Không đọc được phiếu: {error}\n")
    print(title)


if __name__ == "__main__":
    main()
