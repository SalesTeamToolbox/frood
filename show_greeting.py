import sys


def greeting(name):
    print(f"Yo {name}")


if __name__ == "__main__":
    greeting(sys.argv[1])
