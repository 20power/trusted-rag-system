from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=800, ge=1, le=8192)


@dataclass(slots=True)
class RuntimeConfig:
    model_name: str
    device: str
    max_input_tokens: int

    @classmethod
    def from_environment(cls) -> RuntimeConfig:
        return cls(
            model_name=os.getenv(
                "LLM_SERVER_MODEL",
                "Qwen/Qwen2.5-7B-Instruct",
            ).strip(),
            device=os.getenv("LLM_SERVER_DEVICE", "cuda:0").strip(),
            max_input_tokens=max(
                1024,
                int(os.getenv("LLM_SERVER_MAX_INPUT_TOKENS", "8192")),
            ),
        )


class TransformersChatRuntime:
    def __init__(self, config: RuntimeConfig) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "未安装模型运行依赖，请执行：pip install -e '.[model-runtime]'"
            ) from exc

        self.torch = torch
        self.config = config
        self.tokenizer = AutoTokenizer.from_pretrained(config.model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            config.model_name,
            dtype=torch.float16,
        )
        self.model.to(config.device)
        self.model.eval()
        self.lock = Lock()

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        prompt = self.tokenizer.apply_chat_template(
            [message.model_dump() for message in messages],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(
            [prompt],
            return_tensors="pt",
            truncation=True,
            max_length=self.config.max_input_tokens,
        )
        inputs = {key: value.to(self.config.device) for key, value in inputs.items()}
        prompt_tokens = int(inputs["input_ids"].shape[-1])
        generation_args: dict[str, Any] = {
            "max_new_tokens": max_tokens,
            "do_sample": temperature > 0,
            "pad_token_id": self.tokenizer.eos_token_id,
        }
        if temperature > 0:
            generation_args["temperature"] = temperature

        with self.lock, self.torch.inference_mode():
            output = self.model.generate(**inputs, **generation_args)
        generated = output[0, prompt_tokens:]
        content = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        return content, prompt_tokens, int(generated.shape[-1])


runtime: TransformersChatRuntime | None = None
runtime_config = RuntimeConfig.from_environment()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global runtime
    runtime = TransformersChatRuntime(runtime_config)
    yield
    runtime = None


app = FastAPI(
    title="Trusted RAG Local Chat Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, Any]:
    if runtime is None:
        raise HTTPException(status_code=503, detail="model is loading")
    return {
        "status": "ok",
        "model": runtime_config.model_name,
        "device": runtime_config.device,
        "max_input_tokens": runtime_config.max_input_tokens,
    }


@app.post("/v1/chat/completions")
def chat_completions(request: ChatCompletionRequest) -> dict[str, Any]:
    if runtime is None:
        raise HTTPException(status_code=503, detail="model is loading")
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    if any(not message.content.strip() for message in request.messages):
        raise HTTPException(status_code=400, detail="message content 不能为空")

    content, prompt_tokens, completion_tokens = runtime.complete(
        request.messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": runtime_config.model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
