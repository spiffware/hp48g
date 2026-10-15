"""Distinct UserRPL object types; Python lists remain calculator arrays."""
from dataclasses import dataclass


class RPLList(list):
    """HP { list }, distinct from an HP [ vector ]."""


@dataclass(frozen=True)
class BinaryInteger:
    value: int


@dataclass(frozen=True)
class Command:
    name: str


@dataclass(frozen=True)
class Tagged:
    tag: str
    value: object
