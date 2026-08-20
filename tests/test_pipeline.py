"""규격 검증(check_format)과 재시도(generate_one) 단위 테스트.

    python -m unittest discover tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from social_content import pipeline
from social_content.ai import AiCallError
from social_content.platforms import BLOG, INSTAGRAM, X


class FakeClient:
    """정해 둔 응답(또는 예외)을 순서대로 돌려주는 가짜 LLM 클라이언트."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.prompts = []

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return dict(item)


class CheckFormatTest(unittest.TestCase):
    """플랫폼별 규격을 실제로 세는지 확인한다."""

    def test_x_within_limit(self):
        self.assertEqual(pipeline.check_format("x", {"text": "가" * 280}), [])

    def test_x_over_limit(self):
        warnings = pipeline.check_format("x", {"text": "가" * 281})
        self.assertEqual(len(warnings), 1)
        self.assertIn("280자 초과", warnings[0])

    def test_blog_ok(self):
        sections = [{"heading": f"h{i}", "body": "가" * 200} for i in range(3)]
        self.assertEqual(pipeline.check_format("blog", {"sections": sections}), [])

    def test_blog_too_short_and_few_sections(self):
        sections = [{"heading": "h", "body": "가" * 100}]
        warnings = pipeline.check_format("blog", {"sections": sections})
        self.assertEqual(len(warnings), 2)  # 500자 미만 + 소제목 3개 미만

    def test_instagram_hashtag_range(self):
        ok = {"hashtags": ["#t"] * 10}
        self.assertEqual(pipeline.check_format("instagram", ok), [])
        for count in (7, 13):
            warnings = pipeline.check_format("instagram", {"hashtags": ["#t"] * count})
            self.assertEqual(len(warnings), 1, f"해시태그 {count}개는 위반이어야 함")

    def test_missing_fields_do_not_crash(self):
        # 모델이 필드를 빼먹어도 검증기는 죽지 않고 위반으로 센다.
        self.assertEqual(len(pipeline.check_format("x", {})), 0)  # 0자는 초과 아님
        self.assertEqual(len(pipeline.check_format("blog", {})), 2)
        self.assertEqual(len(pipeline.check_format("instagram", {})), 1)


class GenerateOneRetryTest(unittest.TestCase):
    """규격 위반 시 피드백 재시도 로직."""

    def call(self, client, platform=X):
        return pipeline.generate_one(client, platform, "주제", "friendly", "브랜드", "라벨")

    def test_pass_first_try(self):
        client = FakeClient([{"text": "짧은 글"}])
        data = self.call(client)
        self.assertEqual(client.calls, 1)
        self.assertEqual(data["_warnings"], [])

    def test_retry_then_pass_with_feedback(self):
        client = FakeClient([{"text": "가" * 300}, {"text": "고침"}])
        data = self.call(client)
        self.assertEqual(client.calls, 2)
        self.assertEqual(data["_warnings"], [])
        self.assertIn("재작성 요청", client.prompts[1])
        self.assertIn("280자 초과", client.prompts[1])

    def test_keeps_best_after_all_retries(self):
        bad = {"caption": "c", "hashtags": []}
        client = FakeClient([bad, bad, bad])
        data = self.call(client, INSTAGRAM)
        self.assertEqual(client.calls, 1 + pipeline.MAX_FORMAT_RETRIES)
        self.assertEqual(len(data["_warnings"]), 1)

    def test_first_call_error_propagates(self):
        client = FakeClient([AiCallError("boom")])
        with self.assertRaises(AiCallError):
            self.call(client)

    def test_error_during_retry_returns_best(self):
        client = FakeClient([{"text": "가" * 300}, AiCallError("boom")])
        data = self.call(client)
        self.assertEqual(client.calls, 2)
        self.assertEqual(data["text"], "가" * 300)

    def test_blog_retry_feedback_lists_all_violations(self):
        bad = {"title": "t", "sections": [{"heading": "h", "body": "가" * 100}]}
        good = {"title": "t", "sections": [{"heading": f"h{i}", "body": "가" * 200} for i in range(3)]}
        client = FakeClient([bad, good])
        data = self.call(client, BLOG)
        self.assertEqual(client.calls, 2)
        self.assertEqual(data["_warnings"], [])
        self.assertIn("본문 500자 미만", client.prompts[1])
        self.assertIn("소제목 3개 미만", client.prompts[1])


if __name__ == "__main__":
    unittest.main()
