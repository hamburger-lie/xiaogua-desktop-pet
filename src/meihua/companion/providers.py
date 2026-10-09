"""Model providers 小瓜 can talk to.

Anthropic is called through its own SDK. Everyone else is reached through the
OpenAI-compatible Chat Completions endpoint most vendors now offer (see
openai_compat.py), so adding a vendor is one entry here.

Base URLs were checked against each vendor's docs in 2026-09. Model IDs change
often; the listed ones are starting points and the settings window can fetch the
live list from the vendor ("获取模型列表"). `vision` is about the default models:
小瓜 needs image input to read screenshots, and says so when a model has none.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    group: str                       # 国际 / 国内 / 聚合与加速 / 本地 / 自定义
    kind: str                        # "anthropic" or "openai"
    base_url: str = ""
    models: tuple[str, ...] = ()
    env: str = ""                    # environment variable that may hold the key
    key_url: str = ""                # where to get a key
    needs_key: bool = True
    vision: bool = True
    note: str = ""
    token_param: str = "max_tokens"  # newer OpenAI models want max_completion_tokens
    extra: dict = field(default_factory=dict)


PROVIDERS: tuple[Provider, ...] = (
    # ---------------------------------------------------------------- 国际
    Provider("anthropic", "Anthropic Claude", "国际", "anthropic",
             models=("claude-opus-5-5", "claude-sonnet-5", "claude-haiku-4-5"),
             env="ANTHROPIC_API_KEY", key_url="https://console.anthropic.com/settings/keys",
             note="小瓜的默认搭档，看图、调工具最稳。"),
    Provider("openai", "OpenAI", "国际", "openai", "https://api.openai.com/v1",
             ("gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o"),
             env="OPENAI_API_KEY", key_url="https://platform.openai.com/api-keys",
             token_param="max_completion_tokens"),
    Provider("gemini", "Google Gemini", "国际", "openai",
             "https://generativelanguage.googleapis.com/v1beta/openai",
             ("gemini-2.5-pro", "gemini-2.5-flash"),
             env="GEMINI_API_KEY", key_url="https://aistudio.google.com/apikey"),
    Provider("xai", "xAI Grok", "国际", "openai", "https://api.x.ai/v1",
             ("grok-4", "grok-4-fast"), env="XAI_API_KEY", key_url="https://console.x.ai"),
    Provider("mistral", "Mistral", "国际", "openai", "https://api.mistral.ai/v1",
             ("mistral-medium-latest", "pixtral-large-latest", "mistral-large-latest"),
             env="MISTRAL_API_KEY", key_url="https://console.mistral.ai/api-keys"),
    Provider("minimax-intl", "MiniMax（国际）", "国际", "openai", "https://api.minimax.io/v1",
             ("MiniMax-M2", "MiniMax-Text-01"), env="MINIMAX_API_KEY",
             key_url="https://www.minimax.io/platform", vision=False,
             note="国际站密钥只能配国际地址。"),
    # ---------------------------------------------------------------- 国内
    Provider("deepseek", "DeepSeek 深度求索", "国内", "openai", "https://api.deepseek.com/v1",
             ("deepseek-chat", "deepseek-reasoner"), env="DEEPSEEK_API_KEY",
             key_url="https://platform.deepseek.com/api_keys", vision=False,
             note="便宜好用，注册就送额度。"),
    Provider("qwen", "通义千问（阿里云百炼）", "国内", "openai",
             "https://dashscope.aliyuncs.com/compatible-mode/v1",
             ("qwen-vl-max-latest", "qwen-vl-plus", "qwen-max-latest", "qwen-plus"),
             env="DASHSCOPE_API_KEY", key_url="https://bailian.console.aliyun.com/?apiKey=1",
             note=""),
    Provider("doubao", "豆包（火山方舟）", "国内", "openai", "https://ark.cn-beijing.volces.com/api/v3",
             ("doubao-seed-2-1-lite-260915", "doubao-seed-1-6-250615", "doubao-seed-1-6-vision-250815"),
             env="ARK_API_KEY", key_url="https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
             note="模型名也可以填你在方舟控制台建的推理接入点 ID（ep- 开头）。",
             # Seed models think before every reply: ~10 s each time (measured 12.8 s -> 2.6 s off).
             extra={"thinking": {"type": "disabled"}}),
    Provider("zhipu", "智谱 GLM", "国内", "openai", "https://open.bigmodel.cn/api/paas/v4",
             ("glm-4.5v", "glm-4v-plus", "glm-4.5", "glm-4.5-air"),
             env="ZHIPUAI_API_KEY", key_url="https://open.bigmodel.cn/usercenter/apikeys",
             note="按量付费地址，不是 Coding Plan 的地址。"),
    Provider("moonshot", "Kimi（月之暗面）", "国内", "openai", "https://api.moonshot.cn/v1",
             ("kimi-latest", "moonshot-v1-32k-vision-preview", "kimi-k2-0905-preview"),
             env="MOONSHOT_API_KEY", key_url="https://platform.moonshot.cn/console/api-keys",
             note=""),
    Provider("qianfan", "文心（百度千帆）", "国内", "openai", "https://qianfan.baidubce.com/v2",
             ("ernie-4.5-turbo-vl", "ernie-4.5-turbo-128k", "ernie-x1-turbo-32k"),
             env="QIANFAN_API_KEY", key_url="https://console.bce.baidu.com/iam/#/iam/apikey/list",
             note="密钥形如 bce-v3/ALTAK-…"),
    Provider("hunyuan", "腾讯混元", "国内", "openai", "https://api.hunyuan.cloud.tencent.com/v1",
             ("hunyuan-turbos-latest", "hunyuan-vision", "hunyuan-t1-latest"),
             env="HUNYUAN_API_KEY", key_url="https://console.cloud.tencent.com/hunyuan/api-key",
             note="混元正在迁往 TokenHub。"),
    Provider("minimax", "MiniMax（国内）", "国内", "openai", "https://api.minimaxi.com/v1",
             ("MiniMax-M2", "MiniMax-Text-01"), env="MINIMAX_API_KEY",
             key_url="https://platform.minimaxi.com/user-center/basic-information/interface-key",
             vision=False, note="国内站地址多一个 i；国内密钥只能配这个地址。"),
    Provider("stepfun", "阶跃星辰", "国内", "openai", "https://api.stepfun.com/v1",
             ("step-1o-turbo-vision", "step-2-16k", "step-2-mini"),
             env="STEPFUN_API_KEY", key_url="https://platform.stepfun.com/interface-key",
             note="Step Plan 套餐的密钥要用另一个地址：https://api.stepfun.com/step_plan/v1"),
    # ---------------------------------------------------------------- 聚合与加速
    Provider("openrouter", "OpenRouter", "聚合与加速", "openai", "https://openrouter.ai/api/v1",
             ("anthropic/claude-sonnet-4.5", "openai/gpt-5", "google/gemini-2.5-pro"),
             env="OPENROUTER_API_KEY", key_url="https://openrouter.ai/keys",
             note="一个密钥用各家模型；模型名带厂商前缀。"),
    Provider("siliconflow", "硅基流动 SiliconFlow", "聚合与加速", "openai", "https://api.siliconflow.cn/v1",
             ("Qwen/Qwen2.5-VL-72B-Instruct", "deepseek-ai/DeepSeek-V3", "zai-org/GLM-4.5V"),
             env="SILICONFLOW_API_KEY", key_url="https://cloud.siliconflow.cn/account/ak",
             note=""),
    Provider("groq", "Groq", "聚合与加速", "openai", "https://api.groq.com/openai/v1",
             ("meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.3-70b-versatile"),
             env="GROQ_API_KEY", key_url="https://console.groq.com/keys"),
    # ---------------------------------------------------------------- 本地
    Provider("ollama", "Ollama（本机）", "本地", "openai", "http://localhost:11434/v1",
             ("qwen2.5vl:7b", "llama3.2-vision", "qwen3:8b"), needs_key=False,
             key_url="https://ollama.com/download",
             note="先在本机装好 Ollama 并拉取模型；模型要支持工具调用。"),
    Provider("lmstudio", "LM Studio（本机）", "本地", "openai", "http://localhost:1234/v1",
             (), needs_key=False, key_url="https://lmstudio.ai",
             note="在 LM Studio 里启动本地服务器，再点「获取模型列表」。"),
    # ---------------------------------------------------------------- 自定义
    Provider("custom", "自定义（OpenAI 兼容）", "自定义", "openai", "", (),
             note="任何 OpenAI 兼容的地址：填接口地址（到 /v1 为止）、密钥和模型名。"),
)

BY_ID = {p.id: p for p in PROVIDERS}
GROUPS = ("国际", "国内", "聚合与加速", "本地", "自定义")
DEFAULT = "doubao"         # tuned against 豆包 Seed lite; any other works too


def get(provider_id: str) -> Provider:
    return BY_ID.get(provider_id, BY_ID[DEFAULT])
