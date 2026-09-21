"""
敏感信息:工单内容里的手机号是否脱敏。

规格(CLAUDE.md)没有要求脱敏,这组用例是"探测":先把事实测出来,记进 docs/findings/known-issues.md,
要不要作为需求待定。当前实现原样存、原样回——所以"应脱敏"的断言挂成 xfail(strict):
一旦哪天服务加了脱敏,这条会 XPASS 变红,提醒把 known-issues 和本用例一起更新。
"""
import re

import allure
import pytest

from framework.users import Users

pytestmark = [allure.feature("安全"), allure.story("敏感信息脱敏"), pytest.mark.db]

PHONE = "13812345678"
MASKED = re.compile(r"138\*{4}5678")
CONTENT = f"请回电 {PHONE},或者 +86 138-1234-5678,备用 13987654321。身份证 110101199001011234"


@pytest.fixture
def ticket_with_pii(tickets):
    return tickets.create(title=tickets.title("回电咨询"), content=CONTENT)


@allure.title("事实:创建响应 / 详情 / 列表 / 库表 四处手机号原样出现(当前行为,供 findings 记录)")
def test_current_behaviour_phone_is_plain(api, db, ticket_with_pii):
    t = ticket_with_pii
    assert PHONE in t["content"]
    detail = api.get_ticket(t["id"]).expect.ok().resp
    assert PHONE in detail.data["content"]
    listed = next(r for r in api.list_tickets(page=1, size=200).data["records"] if r["id"] == t["id"])
    assert PHONE in listed["content"]
    assert PHONE in db.ticket(t["id"])["content"]
    allure.attach(detail.data["content"], name="返回的 content", attachment_type=allure.attachment_type.TEXT)


@pytest.mark.known_issue
@pytest.mark.xfail(strict=True, reason="KI-001 手机号未脱敏:详情接口原样返回 11 位手机号(docs/findings/known-issues.md)")
@allure.title("期望:详情接口对手机号中间四位脱敏(138****5678)")
def test_detail_masks_phone(api, ticket_with_pii):
    content = api.get_ticket(ticket_with_pii["id"]).expect.ok().resp.data["content"]
    assert PHONE not in content and MASKED.search(content)


@pytest.mark.known_issue
@pytest.mark.xfail(strict=True, reason="KI-001 手机号未脱敏:列表接口原样返回(docs/findings/known-issues.md)")
@allure.title("期望:列表接口对手机号脱敏")
def test_list_masks_phone(api, ticket_with_pii):
    listed = next(r for r in api.list_tickets(page=1, size=200).data["records"] if r["id"] == ticket_with_pii["id"])
    assert PHONE not in listed["content"]


@allure.title("LLM 路径:含手机号的内容会被原样发给挡板(数据出境面;真实模式下等于发给第三方)")
def test_pii_is_sent_to_llm(api, tickets, clean_wiremock_requests):
    t = tickets.create(title=tickets.title("回电"), content=CONTENT)
    reqs = clean_wiremock_requests.requests_to("/mock/llm/classify", body_contains=PHONE)
    assert len(reqs) == 1, "分类请求体里含原始手机号——这是事实记录,不是断言它应该如此"
    draft = api.reply_draft(t["id"]).expect.ok().resp
    assert clean_wiremock_requests.count("/mock/llm/draft", body_contains=PHONE) == 1
    allure.attach(draft.data["draft"], name="草稿", attachment_type=allure.attachment_type.TEXT)
