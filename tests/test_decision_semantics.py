from decimal import Decimal
import unittest

from turtle_quant.core.result import ResultStatus, RuleKind, RuleResult
from turtle_quant.pipeline.decision import DecisionKind, decide


class DecisionRuleKindTests(unittest.TestCase):
    def test_information_unknown_is_annotation_only(self) -> None:
        result = decide(
            (
                RuleResult(
                    rule_id="info.optional",
                    kind=RuleKind.INFORMATION,
                    status=ResultStatus.UNKNOWN,
                ),
            ),
            coverage6=Decimal("1"),
            gg_pct=Decimal("12"),
            required_return_pct=Decimal("5"),
            score_coverage=Decimal("1"),
        )
        self.assertEqual(result.kind, DecisionKind.CANDIDATE)

    def test_evidence_unknown_still_blocks_known_hard_gate_failure(self) -> None:
        result = decide(
            (
                RuleResult(
                    rule_id="evidence.missing",
                    kind=RuleKind.EVIDENCE,
                    status=ResultStatus.UNKNOWN,
                ),
                RuleResult(
                    rule_id="premise.fail",
                    kind=RuleKind.HARD_GATE,
                    status=ResultStatus.FAIL,
                ),
            ),
            coverage6=Decimal("1"),
            gg_pct=Decimal("12"),
            required_return_pct=Decimal("5"),
            score_coverage=Decimal("1"),
        )
        self.assertEqual(result.kind, DecisionKind.NEEDS_REVIEW)


if __name__ == "__main__":
    unittest.main()
