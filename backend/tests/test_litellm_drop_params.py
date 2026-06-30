"""代码层修复回归 · 启动即 litellm.drop_params=True（不依赖 resilient_llm 惰性导入）。

防止 reasoning_effort/thinking 等关思考参数在不支持的模型（qwen3.6-plus 等）上
触发 litellm.UnsupportedParamsError 把 worker tick 打崩。
"""
def test_drop_params_set_at_app_startup():
    import litellm
    import app.main  # noqa: F401  入口导入即设
    assert litellm.drop_params is True
