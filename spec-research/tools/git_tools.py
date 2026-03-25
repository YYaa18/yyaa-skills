#!/usr/bin/env python3
"""
git_checkpoint & git_restore 工具函数
封装 Git 命令，作为 OpenClaw 工具暴露给 Sub-Agent
"""
import subprocess
import json
import re
from typing import Optional


def git_checkpoint(message: str) -> str:
    """
    保存当前 Git 状态作为实验存档。
    相当于 git add . && git commit -m '<message>'
    
    自动处理：
    - 检测未初始化的仓库（自动 git init）
    - 检测无变更的情况（自动 success 返回）
    - 捕获并格式化所有 Git 错误
    """
    try:
        # Step 1: 检查是否在 Git 仓库中
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True
        )
        is_git_repo = result.returncode == 0 and result.stdout.strip() == "true"
        
        if not is_git_repo:
            # 自动初始化
            init_result = subprocess.run(
                ["git", "init"],
                capture_output=True, text=True
            )
            if init_result.returncode != 0:
                return json.dumps({
                    "status": "error",
                    "message": f"git init 失败: {init_result.stderr}"
                }, ensure_ascii=False)

        # Step 2: 检查是否有变更
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True
        )
        has_changes = bool(status_result.stdout.strip())
        
        if not has_changes:
            return json.dumps({
                "status": "success",
                "message": "工作区干净，无需存档（已有快照）",
                "checkpoint_id": subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True
                ).stdout.strip() or "empty"
            }, ensure_ascii=False)

        # Step 3: git add .
        add_result = subprocess.run(
            ["git", "add", "-A"],
            capture_output=True, text=True
        )
        if add_result.returncode != 0:
            return json.dumps({
                "status": "error",
                "message": f"git add 失败: {add_result.stderr}"
            }, ensure_ascii=False)

        # Step 4: git commit
        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True
        )
        if commit_result.returncode != 0:
            return json.dumps({
                "status": "error",
                "message": f"git commit 失败: {commit_result.stderr}"
            }, ensure_ascii=False)

        # 获取 commit hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True
        )
        commit_hash = hash_result.stdout.strip()

        return json.dumps({
            "status": "success",
            "message": f"存档已创建: {commit_hash}",
            "checkpoint_id": commit_hash,
            "commit_message": message,
            "summary": commit_result.stdout.strip().split('\n')[0] if commit_result.stdout.strip() else "无变更"
        }, ensure_ascii=False)

    except FileNotFoundError:
        return json.dumps({
            "status": "error",
            "message": "Git 命令不可用，请确保已安装 Git"
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"未知错误: {str(e)}"
        })


def git_restore() -> str:
    """
    放弃当前修改，回退到最近的存档点。
    相当于 git reset --hard HEAD（保留工作区变更） 或 git checkout . （丢弃工作变更）
    
    优先使用 git stash + reset，保证实验环境干净。
    """
    try:
        # 检查是否有未提交的变更
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True
        )
        has_changes = bool(status_result.stdout.strip())
        
        # 获取当前 HEAD
        head_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True
        )
        current_head = head_result.stdout.strip() if head_result.returncode == 0 else "unknown"
        
        if has_changes:
            # 有变更，先暂存（保留实验记录）
            stash_result = subprocess.run(
                ["git", "stash", "-m", f"experiment-backup-{current_head}"],
                capture_output=True, text=True
            )
            stash_msg = ""
            if stash_result.returncode == 0:
                stash_msg = f"（已 stash: {stash_result.stdout.strip().split(chr(10))[0]}）"
            
            # 丢弃工作区变更
            reset_result = subprocess.run(
                ["git", "reset", "--hard", "HEAD"],
                capture_output=True, text=True
            )
            if reset_result.returncode != 0:
                return json.dumps({
                    "status": "error",
                    "message": f"git reset --hard 失败: {reset_result.stderr}"
                }, ensure_ascii=False)
            
            return json.dumps({
                "status": "success",
                "message": f"已回退到 {current_head}，变更已暂存 {stash_msg}",
                "restored_to": current_head,
                "stashed": has_changes
            }, ensure_ascii=False)
        else:
            # 无变更，简单的 reset
            return json.dumps({
                "status": "success",
                "message": f"工作区已是干净状态（{current_head}）",
                "restored_to": current_head,
                "stashed": False
            }, ensure_ascii=False)

    except FileNotFoundError:
        return json.dumps({
            "status": "error",
            "message": "Git 命令不可用"
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"未知错误: {str(e)}"
        })


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python git_tools.py [checkpoint|restore] [message]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    if cmd == "checkpoint":
        msg = sys.argv[2] if len(sys.argv) > 2 else "checkpoint"
        print(git_checkpoint(msg))
    elif cmd == "restore":
        print(git_restore())
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
