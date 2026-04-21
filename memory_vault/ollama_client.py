
import json
from pydantic import BaseModel
from openai import AsyncOpenAI
from graphiti_core.llm_client.openai_client import OpenAIClient
from graphiti_core.llm_client.config import LLMConfig

class OllamaGraphitiClient(OpenAIClient):
    def __init__(self, config=None, cache=False, client=None, max_tokens=16384, reasoning="minimal", verbosity="low"):
        if config is None:
            config = LLMConfig()
        super().__init__(config, cache, client, max_tokens, reasoning, verbosity)
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)

    async def _create_completion(self, *args, **kwargs):
        kwargs.pop("reasoning", None)
        kwargs.pop("verbosity", None)
        kwargs["response_format"] = {"type": "json_object"}
        return await self.client.chat.completions.create(*args, **kwargs)

    async def _create_structured_completion(self, *args, **kwargs):
        kwargs.pop("reasoning", None)
        kwargs.pop("verbosity", None)
        
        # BaseOpenAIClient calls: model, messages, temperature, max_tokens, response_model, reasoning, verbosity
        # Let us extract response_model from kwargs if passed by name or by index
        response_model = kwargs.pop("response_model", None)
        if not response_model and len(args) > 4:
            response_model = args[4]
            args = args[:4] + args[5:]

        schema = response_model.model_json_schema()
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.get("title", "Response"),
                "schema": schema,
                "strict": True
            }
        }
        res = await self.client.chat.completions.create(*args, **kwargs)
        
        class DummyUsage:
            def __init__(self, prompt_tokens, completion_tokens):
                self.input_tokens = prompt_tokens
                self.output_tokens = completion_tokens
        
        class DummyResponse:
            def __init__(self, text, usage):
                self.output_text = text
                self.usage = usage
                self.refusal = None
        
        usage = DummyUsage(res.usage.prompt_tokens, res.usage.completion_tokens) if res.usage else DummyUsage(0, 0)
        return DummyResponse(res.choices[0].message.content, usage)
