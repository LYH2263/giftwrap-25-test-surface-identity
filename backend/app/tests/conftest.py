"""pytest 测试引导：把数据库隔离到临时 DATA_DIR，再初始化种子数据。

必须在任何 ``app.config`` 导入之前设置 DATA_DIR（config 在导入时读取该变量），
因此环境变量设置放在本文件最顶部、app.* 导入之前。
"""

import os
import sys
import tempfile

# 允许从任意工作目录（含仓库根）直接 `pytest backend/app/tests` 收集：
# 把 backend 目录加入 sys.path，使 `import app.*` 与本目录的夹具模块可用。
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

# 每次 pytest 进程使用独立临时目录，避免污染/依赖开发库 /data/app.db。
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="giftwrap-pytest-")
os.environ["DATA_DIR"] = _TEST_DATA_DIR

from app import seed  # noqa: E402  (依赖上面的 DATA_DIR，必须延后导入)


def pytest_configure(config):
    seed.init_db()
