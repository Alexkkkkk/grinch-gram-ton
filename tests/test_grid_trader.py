from grid_trader import GridTrader


def test_grid_reduces_buy_levels_below_break_even(monkeypatch):
    monkeypatch.setenv("GRID_ALLOW_UNPROFITABLE_ORDERS", "0")
    trader = GridTrader()
    state = trader.build_grid(
        center_price=1.34,
        step_pct=4.0,
        sell_levels=3,
        buy_levels=3,
        token_balance=0.0,
        ton_balance=0.9,
        active=False,
    )

    assert len(state.sell_levels) == 3
    assert len(state.buy_levels) == 2
    assert all(level.amount_ton >= 0.229 for level in state.buy_levels)


def test_buy_creates_adjacent_sell_and_sell_uses_expected_ton():
    trader = GridTrader()
    trader._state.center_price = 1.34
    trader._state.step_pct = 4.0
    trader._state.sell_levels = []
    trader._state.buy_levels = []

    class FakeDeDust:
        sell_min_net_ton = None

        def buy(self, amount):
            return {"ok": True, "usdt_received": 0.155, "tx_hash": "buy-hash"}

        def sell(self, amount, min_net_ton=None):
            self.sell_min_net_ton = min_net_ton
            return {"ok": True, "expected_ton": 0.207, "tx_hash": "sell-hash"}

    fake_dedust = FakeDeDust()
    trader.inject(dedust_client=fake_dedust)
    from grid_trader import GridLevel

    buy = GridLevel(id=-1, side="buy", price_ton=1.288462, amount_ton=0.2)
    assert trader._execute_buy(buy, buy.price_ton)["ok"]
    trader._state.buy_levels.append(buy)
    trader._place_resell(buy)

    sell = trader._state.sell_levels[0]
    assert sell.price_ton == 1.34
    assert sell.amount_token == 0.155
    assert sell.entry_cost_ton > 0.2
    assert trader._execute_sell(sell, sell.price_ton)["ok"]
    assert fake_dedust.sell_min_net_ton == sell.entry_cost_ton + trader._gas_per_tx()
    assert sell.profit_ton == 0.207 - sell.entry_cost_ton - trader._gas_per_tx()
    assert sell.tx_hash == "sell-hash"
