"""分帳與欠款計算。金額一律為整數（台幣元）。"""

from collections import defaultdict


def equal_shares(amount: int, member_ids: list[int], payer_id: int) -> dict[int, int]:
    """把 amount 平分給 member_ids，除不盡的餘數由付款人吸收。

    付款人不在分攤名單內時（例如我付錢買室友要的東西），餘數給名單第一人。
    """
    if amount < 0:
        raise ValueError("金額不可為負")
    if not member_ids:
        raise ValueError("至少要有一個分攤對象")

    base, remainder = divmod(amount, len(member_ids))
    shares = {m: base for m in member_ids}
    absorber = payer_id if payer_id in shares else member_ids[0]
    shares[absorber] += remainder
    return shares


def validate_shares(amount: int, shares: dict[int, int]) -> None:
    """自訂分攤額的檢查：不可為負、加總必須等於總額。"""
    if not shares:
        raise ValueError("至少要有一個分攤對象")
    if any(v < 0 for v in shares.values()):
        raise ValueError("分攤額不可為負")
    total = sum(shares.values())
    if total != amount:
        raise ValueError(f"分攤額加總 {total} 不等於總額 {amount}")


def pairwise_debts(expenses: list[dict]) -> dict[tuple[int, int], int]:
    """算出「誰欠誰多少」。

    expenses 每筆是 {"payer_id": int, "shares": {member_id: amount}}。
    回傳 {(欠的人, 被欠的人): 金額}，只留正數，雙向已相抵。
    """
    raw: dict[tuple[int, int], int] = defaultdict(int)
    for e in expenses:
        payer = e["payer_id"]
        for member_id, amt in e["shares"].items():
            if member_id != payer and amt:
                raw[(member_id, payer)] += amt

    netted: dict[tuple[int, int], int] = {}
    done: set[tuple[int, int]] = set()
    for debtor, creditor in raw:
        if (debtor, creditor) in done:
            continue
        done.add((debtor, creditor))
        done.add((creditor, debtor))
        net = raw[(debtor, creditor)] - raw.get((creditor, debtor), 0)
        if net > 0:
            netted[(debtor, creditor)] = net
        elif net < 0:
            netted[(creditor, debtor)] = -net
    return netted


def _demo() -> None:
    # 平分整除
    assert equal_shares(300, [1, 2, 3], payer_id=1) == {1: 100, 2: 100, 3: 100}

    # 除不盡：餘數給付款人
    assert equal_shares(100, [1, 2, 3], payer_id=2) == {1: 33, 2: 34, 3: 33}
    assert equal_shares(100, [1, 2, 3, 4, 5, 6, 7], payer_id=1) == {
        1: 16, 2: 14, 3: 14, 4: 14, 5: 14, 6: 14, 7: 14
    }

    # 付款人不在分攤名單 → 餘數給第一人
    assert equal_shares(100, [2, 3, 4], payer_id=1) == {2: 34, 3: 33, 4: 33}

    # 加總永遠等於總額
    for amt in range(0, 200):
        for n in range(1, 8):
            ids = list(range(1, n + 1))
            assert sum(equal_shares(amt, ids, payer_id=1).values()) == amt

    # 自訂分攤額檢查
    validate_shares(100, {1: 60, 2: 40})
    for bad in ({1: 60, 2: 30}, {1: -10, 2: 110}, {}):
        try:
            validate_shares(100, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"應該要擋下 {bad}")

    # 欠款：單筆，付款人不算欠自己
    assert pairwise_debts([{"payer_id": 1, "shares": {1: 34, 2: 33, 3: 33}}]) == {
        (2, 1): 33, (3, 1): 33
    }

    # 欠款：雙向相抵
    assert pairwise_debts([
        {"payer_id": 1, "shares": {1: 50, 2: 50}},   # 2 欠 1 五十
        {"payer_id": 2, "shares": {1: 30, 2: 30}},   # 1 欠 2 三十
    ]) == {(2, 1): 20}

    # 欠款：完全抵銷就不出現
    assert pairwise_debts([
        {"payer_id": 1, "shares": {1: 50, 2: 50}},
        {"payer_id": 2, "shares": {1: 50, 2: 50}},
    ]) == {}

    # 欠款：付款人自己全額負擔 → 沒人欠錢
    assert pairwise_debts([{"payer_id": 1, "shares": {1: 100}}]) == {}

    print("split.py 全部檢查通過")


if __name__ == "__main__":
    _demo()
