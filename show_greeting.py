import random
import sys

BANNER = r"""
 ╔═══════════════════════════════════════════════════════════╗
 ║                                                           ║
 ║     █████╗  ██████╗ ███████╗███╗   ██╗████████╗           ║
 ║    ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝           ║
 ║    ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║               ║
 ║    ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║               ║
 ║    ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║  42           ║
 ║    ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝              ║
 ║                                                           ║
 ║    Don't Panic. The Guide is online.                      ║
 ║                                                           ║
 ╚═══════════════════════════════════════════════════════════╝
"""

QUOTES = [
    # Douglas Adams (~75%)
    '"Time is an illusion. Lunchtime doubly so." — Douglas Adams',
    '"I love deadlines. I love the whooshing noise they make as they go by." — Douglas Adams',
    '"The ships hung in the sky in much the same way that bricks don\'t." — Douglas Adams',
    '"Don\'t Panic." — Douglas Adams',
    (
        '"In the beginning the Universe was created. This has made a lot of'
        ' people very angry and been widely regarded as a bad move." — Douglas Adams'
    ),
    (
        '"A common mistake that people make when trying to design something'
        " completely foolproof is to underestimate the ingenuity of complete"
        ' fools." — Douglas Adams'
    ),
    '"Would it save you a lot of time if I just gave up and went mad now?" — Douglas Adams',
    (
        '"For a moment, nothing happened. Then, after a second or so,'
        ' nothing continued to happen." — Douglas Adams'
    ),
    # Monty Python (~25%)
    '"\'Tis but a scratch!" — The Black Knight',
    '"We are the knights who say... Ni!" — Monty Python',
    '"Nobody expects the Spanish Inquisition!" — nor a working build on the first try.',
    (
        '"Strange women lying in ponds distributing swords is no basis for a'
        ' system of government." — nor for task orchestration, which is why we use a queue.'
    ),
]


def greeting(name):
    print(BANNER)
    if name:
        print(f"  Welcome, {name}. The Answer is 42.")
    print(f"  {random.choice(QUOTES)}")
    print()


if __name__ == "__main__":
    greeting(sys.argv[1] if len(sys.argv) > 1 else "")
