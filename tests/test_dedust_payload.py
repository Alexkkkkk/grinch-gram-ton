from dedust_client import dedust_client
from pytoniq_core import Address


def test_sell_payload_uses_legacy_dedust_vault_format():
    recipient = Address(
        "0:99d74121f08279b050ba24a9fe62b6a5305e39064e5f90d4fa4aa4c7488446c5"
    )
    pool = Address(
        "0:3e5ffca8ddfcf36c36c9ff46f31562aab51b9914845ad6c26cbde649d58a5588"
    )
    body = dedust_client._build_sell_transfer_body(
        recipient=recipient,
        pool_addr=pool,
        usdt_nano=332002,
        min_out_nano=237043000,
        deadline=1788295800,
        fwd_nano=180000000,
    )

    transfer = body.begin_parse()
    assert transfer.load_uint(32) == 0x0F8A7EA5
    transfer.load_uint(64)
    assert transfer.load_coins() == 332002
    assert transfer.load_address() == pool
    assert transfer.load_address() == recipient
    assert transfer.load_maybe_ref() is None
    assert transfer.load_coins() == 180000000
    forward = transfer.load_ref().begin_parse()

    assert forward.load_uint(32) == 0xE3A0D482
    assert forward.load_address() == pool
    assert forward.load_bit() == 0
    assert forward.load_coins() == 237043000
    assert forward.load_maybe_ref() is None

    params = forward.load_ref().begin_parse()
    assert params.load_uint(32) == 1788295800
    assert params.load_address() == recipient
    assert params.load_address() is None
    assert params.load_maybe_ref() is None
    assert params.load_maybe_ref() is None