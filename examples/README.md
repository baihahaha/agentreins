# Examples

Each example runs offline with `FakeModel`, unless its name ends in `_live.py` (those call a real provider and need an API key). The offline ones run in CI, so they always work.

| Example | Shows |
|---|---|
| [01_hello_tool.py](01_hello_tool.py) | An agent that answers by calling a Python function |
| [01_hello_tool_live.py](01_hello_tool_live.py) | The same agent with OpenAI |

```bash
uv run python examples/01_hello_tool.py
```
