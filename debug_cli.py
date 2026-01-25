import os
import getpass

from rag_agent.graph_builder import build_graph


def init_environment():
    if "GOOGLE_API_KEY" not in os.environ:
        os.environ["GOOGLE_API_KEY"] = getpass.getpass("Enter your Google API Key: ")


def main():
    init_environment()
    graph = build_graph()

    print("\n=== Agent Ready ===")
    print("Type 'exit' to quit.\n")

    while True:
        user_input = input("User: ")
        if user_input.lower() in ["exit", "quit", "q"]:
            print("see you!")
            break

        initial_state = {"messages": [{"role": "user", "content": user_input}]}
        for chunk in graph.stream(initial_state):
            for node, update in chunk.items():
                print(f"--- Node: {node} ---")
                if "messages" in update:
                    last_msg = update["messages"][-1]
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        print(f"Calling Tool: {last_msg.tool_calls[0]['name']}")
                    else:
                        content = last_msg.content
                        if isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and "text" in part:
                                    print(part["text"])
                        else:
                            print(content)
                print("\n")


if __name__ == "__main__":
    main()