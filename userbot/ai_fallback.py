import json
import logging
import google.generativeai as genai
import httpx
import config

logger = logging.getLogger("userbot.ai_fallback")

if config.GEMINI_API_KEY:
    genai.configure(api_key=config.GEMINI_API_KEY)


SYSTEM_PROMPT = """You are an agent navigating a Telegram bot to buy a VPN subscription.
The target plan is: {plan_name} ({plan_data}GB).

Analyze the recent messages and keyboard buttons from the source bot.
Determine the next action to take.

Reply ONLY with a JSON object in this exact format:
{{"action": "send_text" | "click_inline" | "click_reply" | "extract_url", "value": "text_to_send_or_button_text_or_url"}}

Actions:
- "send_text": type and send the value as a message
- "click_inline": find and click an inline keyboard button containing the value text
- "click_reply": find and click a reply keyboard button containing the value text
- "extract_url": a URL (VPN config link, subscription URL, etc.) was found in the conversation; return it as the value

Rules:
- The value must be the EXACT text shown on the button or the exact text to send
- Choose the button that matches the target plan
- If a button contains the target plan's data amount, prefer it
- If you see a URL in any message (especially a VPN config or subscription link), use extract_url and put the full URL as the value
- Only output the JSON object, nothing else"""


def _extract_buttons(reply_markup) -> list[str]:
    buttons = []
    if reply_markup is None:
        return buttons
    if isinstance(reply_markup, str):
        return buttons
    try:
        if hasattr(reply_markup, "keyboard"):
            for row in reply_markup.keyboard:
                for b in row:
                    text = b.text if hasattr(b, "text") else str(b)
                    buttons.append(text)
        if hasattr(reply_markup, "inline_keyboard"):
            for row in reply_markup.inline_keyboard:
                for b in row:
                    text = b.text if hasattr(b, "text") else str(b)
                    buttons.append(text)
    except Exception:
        pass
    return buttons


async def fallback_ai_agent(chat_history: list[dict], plan: dict) -> dict | None:
    if not config.GEMINI_API_KEY:
        logger.warning("Gemini API key not configured, skipping AI fallback")
        return None

    formatted_history = []
    for msg in chat_history:
        sender = "Bot" if msg.get("from_user") else "User"
        text = msg.get("text", "")
        buttons = _extract_buttons(msg.get("reply_markup"))
        entry = f"[{sender}]: {text}"
        if buttons:
            entry += f"\nButtons: {', '.join(buttons)}"
        formatted_history.append(entry)

    conversation = "\n".join(formatted_history)
    system = SYSTEM_PROMPT.format(plan_name=plan["name"], plan_data=plan["data_gb"])
    prompt = f"{system}\n\nRecent conversation:\n{conversation}\n\nWhat is the next action?"

    text = None

    try:
        model = genai.GenerativeModel(config.GEMINI_MODEL)
        response = await model.generate_content_async(prompt)
        text = response.text.strip()
        logger.info("Gemini SDK call succeeded")
    except Exception as e:
        logger.warning(f"Gemini SDK failed ({type(e).__name__}: {e}), trying REST API fallback")
        try:
            resp = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}",
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=30.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                logger.info("Gemini REST API fallback succeeded")
            else:
                logger.error(f"Gemini REST API returned {resp.status_code}: {resp.text[:300]}")
                return None
        except Exception as e2:
            logger.error(f"Gemini REST API fallback also failed: {e2}")
            return None

    if not text:
        return None

    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        if text.endswith("```"):
            text = text[:-3]

    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response as JSON: {e}")
        return None

    if "action" not in result or "value" not in result:
        logger.error(f"Invalid AI response format: {result}")
        return None

    if result["action"] not in ("send_text", "click_inline", "click_reply", "extract_url"):
        logger.error(f"Invalid action: {result['action']}")
        return None

    logger.info(f"AI fallback action: {result}")
    return result
