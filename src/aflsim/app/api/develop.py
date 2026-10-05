"""DEVELOP A TEAM: browse the bot library, read any bot's source, write code bots and define LLM bots."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aflsim.app import services as S

router = APIRouter(prefix="/api/develop", tags=["develop"])


class CodeBot(BaseModel):
    name: str                       # community/my_bot or drafts/my_bot
    text: str
    overwrite: bool = False


class LLMBot(BaseModel):
    name: str
    config: dict
    overwrite: bool = False


@router.get("/bots")
def bots():
    return S.list_bots()


@router.get("/source")
def source(spec: str):
    try:
        return S.bot_source(spec)
    except (KeyError, FileNotFoundError) as e:
        raise HTTPException(404, str(e))


@router.get("/templates")
def templates():
    return {"code": S.code_template(), "llm_types": S.LLM_TYPES,
            "llm_examples": {"jev": {"backend": "http", "model": "jev-1.13.0", "prompt": "v3", "x_step": 10, "y_step": 10, "sample": False},
                             "llm": {"provider": "openai:gpt-5.6-terra", "temperature": 1.0, "reasoning_effort": "low", "cache": True},
                             "coached": {"coach": "gpt-5.6-terra", "player": "deepseek:deepseek-chat", "pack": "ric", "coach_every": 12.0, "cache": True}}}


@router.post("/code")
def save_code(b: CodeBot):
    try:
        return {"spec": S.save_code_bot(b.name, b.text, b.overwrite)}
    except (ValueError, SyntaxError) as e:
        raise HTTPException(400, str(e))
    except FileExistsError as e:
        raise HTTPException(409, str(e))


@router.post("/llm/preview")
def preview_llm(b: LLMBot):
    try:
        return {"toml": S.llm_toml(b.config)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/llm")
def save_llm(b: LLMBot):
    try:
        return {"spec": S.save_llm_bot(b.name, b.config, b.overwrite)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileExistsError as e:
        raise HTTPException(409, str(e))
