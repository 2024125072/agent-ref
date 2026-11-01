from agent.core.graph import build_graph, create_demo_input
import json


if __name__ == "__main__":
    print("[LangGraph 데모] 실제 LLM/Tool 호출 없이 3단계 실행")
    app = build_graph()
    for event in app.stream(create_demo_input(), stream_mode="updates"):
        print(json.dumps(event, indent=2, ensure_ascii=False))