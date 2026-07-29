"""
HNSW 索引构建进度监控脚本
用法: cd backend && venv/Scripts/python.exe scripts/watch_index.py
每30秒刷新一次，Ctrl+C 退出
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.qdrant_client import get_qdrant_client

def main():
    qdrant = get_qdrant_client()
    print("=" * 55)
    print("  Qdrant HNSW 索引构建进度监控")
    print("  每 30s 刷新 | Ctrl+C 退出")
    print("=" * 55)

    last_indexed = 0
    last_time = time.time()

    while True:
        info = qdrant.get_collection_info()
        indexed = info.get('indexed_vectors_count', 0)
        total = info.get('vectors_count', 0)
        status = info.get('status', 'unknown')
        pct = indexed / total * 100 if total > 0 else 0

        now = time.time()
        dt = now - last_time
        speed = (indexed - last_indexed) / dt if dt > 0 and last_indexed > 0 else 0
        eta = (total - indexed) / speed if speed > 0 else -1

        if eta > 3600:
            eta_str = f"{eta/3600:.1f}h"
        elif eta > 60:
            eta_str = f"{eta/60:.0f}min"
        elif eta > 0:
            eta_str = f"{eta:.0f}s"
        else:
            eta_str = "--"

        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)

        print(
            f"[{time.strftime('%H:%M:%S')}] {bar} {pct:.1f}%  "
            f"{indexed:,}/{total:,}  "
            f"speed={speed:,.0f}/s  ETA={eta_str}  "
            f"status={status}"
        )

        if indexed >= total and status == 'green':
            print("\n✅ HNSW 索引构建完成！Collection 状态: green")
            break

        last_indexed = indexed
        last_time = now
        time.sleep(30)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 已退出监控（索引构建不受影响，Qdrant 后台继续）")
