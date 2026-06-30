"""代码层修复回归 · 重放历史前剔除 thinking/reasoning content 块。

根因：qwen3.6-plus 把推理作为 [{"type":"thinking",...}] 放进 assistant content；agent 多轮
循环回填该消息时 qwen 报 `Unexpected item type in content`。_sanitize_messages 把这些块剔除。
"""
from langchain_core.messages import AIMessage, HumanMessage
from app.services.resilient_llm import _sanitize_message_content, _sanitize_messages


def test_strip_thinking_flattens_to_string():
    content = [
        {"type": "thinking", "thinking": "let me think..."},
        {"type": "text", "text": "你好"},
        {"type": "thinking", "thinking": "more"},
        {"type": "text", "text": "！"},
    ]
    out = _sanitize_message_content(content)
    assert out == "你好！"  # thinking 剔除 + 纯 text 收敛成字符串


def test_all_thinking_becomes_empty():
    content = [{"type": "thinking", "thinking": "a"}, {"type": "reasoning", "reasoning": "b"}]
    assert _sanitize_message_content(content) == ""


def test_keeps_multimodal_list_when_image_present():
    content = [
        {"type": "thinking", "thinking": "x"},
        {"type": "text", "text": "看图"},
        {"type": "image_url", "image_url": {"url": "http://x/y.png"}},
    ]
    out = _sanitize_message_content(content)
    assert isinstance(out, list)
    assert {"type": "image_url", "image_url": {"url": "http://x/y.png"}} in out
    assert all(p.get("type") != "thinking" for p in out)


def test_plain_string_untouched():
    assert _sanitize_message_content("hello") == "hello"


def test_sanitize_messages_rewrites_only_list_content():
    msgs = [
        HumanMessage(content="问题"),
        AIMessage(content=[{"type": "thinking", "thinking": "t"}, {"type": "text", "text": "答"}]),
    ]
    out = _sanitize_messages(msgs)
    assert out[0].content == "问题"          # 字符串原样
    assert out[1].content == "答"            # list 被收敛、thinking 剔除
    # 不改原对象
    assert isinstance(msgs[1].content, list)
