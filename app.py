import json
import os
import re
import time

import requests

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="public", static_url_path="")

MODELS = [
    os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"),
    "gemini-flash-latest",
    "gemini-3.8-flash",
]

TUTOR_SYSTEM = (
    "You are StudyMate, a friendly, clear tutor for students. "
    "Explain simply with a short example. Keep answers under 150 words. "
    "If a document is provided, answer only from it and say so if the answer is not there."
)

session = requests.Session()


def gemini(prompt, system=None, max_tokens=500):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing in .env")

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.6},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    last_error = ""
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            try:
                r = session.post(url, params={"key": key}, json=body, timeout=25)
            except requests.RequestException as e:
                last_error = f"Network error: {e}"
                break
            if r.status_code == 200:
                try:
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    last_error = "The AI returned an empty answer."
                    break
            last_error = f"Gemini error {r.status_code} on {model}"
            if r.status_code in (429, 500, 503) and attempt == 0:
                time.sleep(0.7)
                continue
            break

    raise RuntimeError("The AI is busy right now. Please try again. (" + last_error + ")")


@app.get("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message")
    context = data.get("context") or ""
    if not isinstance(message, str) or not message.strip():
        return jsonify(error="Message is required."), 400

    doc = context[:12000] if isinstance(context, str) else ""
    prompt = f"DOCUMENT:\n{doc}\n\nQUESTION: {message}" if doc else message
    try:
        return jsonify(reply=gemini(prompt, TUTOR_SYSTEM))
    except Exception as e:
        app.logger.error("Chat error: %s", e)
        return jsonify(error=str(e)), 500


@app.post("/api/quiz")
def quiz():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        return jsonify(error="Topic is required."), 400

    prompt = (
        f'Create 5 multiple-choice questions for a student on "{topic[:120]}". '
        "Return only JSON, no other text: an array of "
        '{"q": string, "o": [4 strings], "a": index of the correct option 0-3}.'
    )
    try:
        raw = gemini(prompt, max_tokens=1500)
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        questions = json.loads(match.group(0) if match else raw)
        ok = (
            isinstance(questions, list) and len(questions) > 0
            and all(
                isinstance(x, dict) and x.get("q") and isinstance(x.get("o"), list)
                and len(x["o"]) == 4 and isinstance(x.get("a"), int) and 0 <= x["a"] <= 3
                for x in questions
            )
        )
        if not ok:
            raise ValueError("Bad quiz format. Click Generate again.")
        return jsonify(questions=questions[:5])
    except Exception as e:
        app.logger.error("Quiz error: %s", e)
        return jsonify(error=f"Could not create the quiz: {e}"), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 3000)), debug=True)