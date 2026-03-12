"""
开发/测试配置

用于控制抓取行为，方便测试
"""

# 抓取数量限制
# -1 = 不限制，抓取全部
# 10 = 每个源最多抓取10条
FETCH_LIMIT = 10

# 是否跳过验证步骤（加快测试速度）
SKIP_VERIFICATION = False

# 是否跳过翻译步骤
SKIP_TRANSLATION = False

# 是否跳过精炼步骤
SKIP_REFINING = False

# 调试模式（打印更多日志）
DEBUG_MODE = False
