from agent.sandbox_runtime.manual_review import ManualReviewStore


def test_manual_review_is_durable_redacted_and_read_only(sandbox_root):
    s=ManualReviewStore(sandbox_root)
    item=s.create(transaction_id="tx",reason="unknown outcome Authorization: secret",resource="data/a",operation="WRITE_FILE",state_observed="partial",state_expected="after",original_error="token=secret",rollback_error=None)
    s2=ManualReviewStore(sandbox_root)
    loaded=s2.inspect(item.review_id)
    assert loaded.transaction_id=="tx"
    text=str(loaded.to_dict()).lower()
    assert "secret" not in text and "authorization" not in text and "token=" not in text
    assert len(s2.list())==1
