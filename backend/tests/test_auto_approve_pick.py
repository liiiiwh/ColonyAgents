"""auto_approve 选项选择：挑肯定/推进项，不盲取 options[0]（修选项顺序不巧时静默选错的漏洞）。"""
from app.domain.auto_approve import pick_auto_option


def test_propose_confirm_proceed_first():
    assert pick_auto_option(["就这么干", "我要调整", "我自己说想法"]) == "就这么干"


def test_negative_first_still_picks_affirmative():
    # 漏洞 case：取消/保守项被放第一 → 必须挑后面的推进项，不能盲取 options[0]
    assert pick_auto_option(["取消", "继续执行"]) == "继续执行"
    assert pick_auto_option(["先不发，等我看", "直接发布"]) == "直接发布"
    assert pick_auto_option(["放弃", "重试", "继续"]) == "继续"


def test_publish_approval():
    assert pick_auto_option(["驳回重写", "通过发布"]) == "通过发布"


def test_pure_choice_falls_back_to_first():
    # 纯多选（无肯定/否定语义）→ 回退 options[0]（super 默认推荐项放前）
    assert pick_auto_option(["方案A", "方案B", "方案C"]) == "方案A"


def test_destructive_confirm_proceeds_under_yolo():
    # YOLO 语义下 auto=推进：确认删除（不是盲取第一个的"保留"）
    assert pick_auto_option(["保留", "确认删除"]) == "确认删除"


def test_empty_safe_default():
    assert pick_auto_option([]) == "同意"
    assert pick_auto_option(None) == "同意"
