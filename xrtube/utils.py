from enum import Enum

class AutoStrEnum(Enum):
    """Enum where auto() value gives the name of the member"""
    @staticmethod
    def _generate_next_value_(name: str, *_):
        return name


def int_ratio(width, height) -> tuple[int, int]:
    """Return aspect ratio in int:int form for a width and height."""
    def greatest_common_divisor(a, b):
        while a:
            a, b = b % a, a
        return b
    gcd = greatest_common_divisor(width, height)
    return int(width / gcd), int(height / gcd)
