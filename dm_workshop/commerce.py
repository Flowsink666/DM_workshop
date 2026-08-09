"""Provider-neutral commerce contracts reserved for a future implementation."""

from __future__ import annotations

from typing import Protocol, TypedDict


class CommerceQuote(TypedDict):
    item_id: str
    quantity: int
    total_gp: int


class CommerceProvider(Protocol):
    """Abstract boundary for future shops, vendors, or marketplaces."""

    def quote_buy(self, campaign_id: str, item_id: str, quantity: int) -> CommerceQuote:
        ...

    def quote_sell(self, campaign_id: str, item_id: str, quantity: int) -> CommerceQuote:
        ...

    def buy(self, campaign_id: str, owner_id: str, item_id: str,
            quantity: int) -> dict:
        ...

    def sell(self, campaign_id: str, owner_id: str, stack_id: str,
             quantity: int) -> dict:
        ...
