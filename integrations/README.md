# SentinelCorp Agent Integrations

Drop-in company risk profiling for any AI agent framework.

## LangChain

```python
from integrations.langchain_tool import get_sentinelcorp_tools

tools = get_sentinelcorp_tools()
agent = initialize_agent(tools, llm, agent="zero-shot-react-description")
agent.run("Do due diligence on Sahara India — is it high risk?")
```

## CrewAI

```python
from integrations.crewai_tool import SentinelCorpProfileTool, SentinelCorpDebarredTool

compliance_agent = Agent(
    role="Compliance Analyst",
    goal="Assess risk of Indian companies",
    tools=[SentinelCorpProfileTool(), SentinelCorpDebarredTool()],
)
```

## OpenAI Function Calling

```python
from integrations.openai_functions import SENTINELCORP_FUNCTIONS, handle_sentinelcorp_call

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Is Sahara India safe to do business with?"}],
    functions=SENTINELCORP_FUNCTIONS,
)
```

## MCP Server (Claude, Cursor)

```json
{
  "mcpServers": {
    "sentinelcorp": {
      "command": "python",
      "args": ["integrations/mcp_server.py"]
    }
  }
}
```

## Python SDK

```python
from sentinelcorp import SentinelCorp

client = SentinelCorp()
profile = client.profile("Sahara India")
print(profile["overall_risk_score"])  # 66.5
```
