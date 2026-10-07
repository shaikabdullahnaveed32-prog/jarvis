import readline  # noqa: F401  (arrow-key history in the prompt)

from core.brain import Brain


def main():
    brain = Brain()
    print("JARVIS online. Type 'exit' to quit.\n")
    while True:
        try:
            text = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nJARVIS: Shutting down, sir.")
            break
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            print("JARVIS: Shutting down, sir.")
            break
        print(f"\nJARVIS: {brain.ask(text)}\n")


if __name__ == "__main__":
    main()
