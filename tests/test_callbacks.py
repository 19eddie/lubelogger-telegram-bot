"""Unit tests for the callback_data codec (bot/callbacks.py)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bot.callbacks import (
    NO_TOKEN,
    TELEGRAM_CALLBACK_DATA_LIMIT,
    Callback,
    CallbackAction,
    CallbackDecodeError,
    decode,
    encode,
    new_token,
)


def test_action_values_are_the_design_table() -> None:
    assert {action.name: action.value for action in CallbackAction} == {
        "CANCEL": "cx",
        "SAVE": "sv",
        "EDIT": "ed",
        "FIELD": "fp",
        "KEEP": "kp",
        "CHOICE": "ch",
        "ODO_CONFIRM": "oc",
        "ODO_REENTER": "oe",
        "LOG_ANOTHER": "la",
        "LATEST_OPEN": "lo",
        "LATEST_BACK": "lb",
        "OPTIONS_OPEN": "oo",
        "OPTIONS_BACK": "ob",
        "VEHICLE_SET": "vs",
        "LANG_SET": "ls",
        "ABANDON_YES": "ay",
        "ABANDON_NO": "an",
    }


def test_action_values_are_two_ascii_lowercase_letters() -> None:
    for action in CallbackAction:
        assert len(action.value) == 2
        assert action.value.isascii() and action.value.isalpha() and action.value.islower()


def test_constants() -> None:
    assert TELEGRAM_CALLBACK_DATA_LIMIT == 64
    assert NO_TOKEN == "-"


def test_new_token_is_eight_urlsafe_characters_and_unique() -> None:
    tokens = {new_token() for _ in range(50)}
    assert len(tokens) == 50
    for token in tokens:
        assert len(token) == 8
        assert token.isascii()
        assert set(token) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        assert ":" not in token


def test_encode_without_arg_uses_two_parts() -> None:
    assert encode(CallbackAction.CANCEL, "abcd1234") == "cx:abcd1234"


def test_encode_defaults_to_no_token() -> None:
    assert encode(CallbackAction.OPTIONS_BACK) == "ob:-"


def test_encode_with_arg_uses_three_parts() -> None:
    assert encode(CallbackAction.FIELD, "abcd1234", 2) == "fp:abcd1234:2"


def test_encode_accepts_zero_as_a_real_arg() -> None:
    assert encode(CallbackAction.CHOICE, "abcd1234", 0) == "ch:abcd1234:0"
    assert decode("ch:abcd1234:0").arg == 0


def test_roundtrip_examples() -> None:
    token = new_token()
    assert decode(encode(CallbackAction.SAVE, token)) == Callback(CallbackAction.SAVE, token, None)
    assert decode(encode(CallbackAction.VEHICLE_SET, NO_TOKEN, 4711)) == Callback(
        CallbackAction.VEHICLE_SET, NO_TOKEN, 4711
    )


def test_decoded_in_flow_reflects_the_token() -> None:
    assert decode(encode(CallbackAction.EDIT, new_token())).in_flow is True
    assert decode(encode(CallbackAction.LATEST_BACK)).in_flow is False


def test_every_action_stays_within_the_byte_budget() -> None:
    token = new_token()
    for action in CallbackAction:
        for arg in (None, 0, 2_147_483_647):
            data = encode(action, token, arg)
            assert len(data.encode("utf-8")) <= TELEGRAM_CALLBACK_DATA_LIMIT
            assert len(data.encode("utf-8")) <= 22


@pytest.mark.parametrize(
    "kwargs",
    [
        {"token": ""},
        {"token": "ab:cd"},
        {"token": "abcd1234", "arg": -1},
        {"token": "abcd1234", "arg": 10_000_000_000},
        {"token": "abcd1234", "arg": True},
        {"token": "abcd1234", "arg": "2"},
    ],
)
def test_encode_rejects_invalid_input(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        encode(CallbackAction.FIELD, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "data",
    [
        "",
        "cx",
        "cx:",
        "zz:abcd1234",
        "cx:abcd1234:2:3",
        "fp:abcd1234:x",
        "fp:abcd1234:-1",
        "fp:abcd1234:1.5",
        "fp:abcd1234:٣",
        "fp:abcd1234:12345678901",
        "CX:abcd1234",
    ],
)
def test_decode_rejects_malformed_data(data: str) -> None:
    with pytest.raises(CallbackDecodeError):
        decode(data)


def test_decode_error_carries_the_offending_data() -> None:
    with pytest.raises(CallbackDecodeError) as excinfo:
        decode("zz:abcd1234")
    assert excinfo.value.data == "zz:abcd1234"
    assert "zz" in excinfo.value.hint


# --- Property tests ---------------------------------------------------------------

#: Every character `secrets.token_urlsafe` can emit, i.e. the Flow_Token alphabet.
_TOKEN_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

#: Tokens the codec must accept: the out-of-flow placeholder, real Flow_Tokens, and any
#: other separator-free string of the same alphabet up to the 8 characters of the budget.
_tokens = st.one_of(
    st.just(NO_TOKEN),
    st.builds(new_token),
    st.text(alphabet=_TOKEN_ALPHABET, min_size=1, max_size=8),
)

#: Arguments in the allowed range: absent, or a non-negative integer of at most 10 digits.
_args = st.one_of(st.none(), st.integers(min_value=0, max_value=10**10 - 1))


@settings(max_examples=100)
@given(action=st.sampled_from(list(CallbackAction)), token=_tokens, arg=_args)
def test_property_callback_data_roundtrip_and_budget(
    action: CallbackAction, token: str, arg: int | None
) -> None:
    """Property 3: callback_data round-trips and stays within 64 bytes.

    # Feature: improve-ux, Property 3: callback_data round-trips and stays within 64 bytes
    **Validates: Requirements 11.3, NF-1.4**
    """
    data = encode(action, token, arg)

    assert decode(data) == Callback(action=action, token=token, arg=arg)
    assert len(data.encode("utf-8")) <= TELEGRAM_CALLBACK_DATA_LIMIT
