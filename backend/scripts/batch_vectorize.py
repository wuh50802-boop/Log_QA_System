"""
向后兼容入口 —— 实际逻辑已迁移到 services/batch_vectorize.py。

保留此文件是为了兼容已有文档和习惯用法：
    python scripts/batch_vectorize.py --rebuild
    python scripts/batch_vectorize.py --resume

新代码请直接：
    from services.batch_vectorize import batch_vectorize
    # 或 CLI：
    python -m services.batch_vectorize --rebuild
"""
import sys
import os
# scripts/ 的父目录是 backend/，加入 sys.path 才能 import services.*
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.batch_vectorize import main  # noqa: E402

if __name__ == "__main__":
    main()
