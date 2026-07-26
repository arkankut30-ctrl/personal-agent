"""
app.py
------
النسخة الاحترافية من خادم الوكيل الشخصي: جلسات محادثة متعددة،
إعدادات (اختيار نموذج، تشغيل/إيقاف تأكيد أوامر shell)، وفحص تحديثات
من GitHub — كل شيء يعمل محليًا على جهازك.

التشغيل:
    pip install -r requirements_pro.txt
    ollama serve            # غالبًا يعمل تلقائيًا كخدمة
    python3 app.py
    ثم افتح المتصفح على: http://localhost:5000
"""

import requests
from flask import Flask, request, jsonify, render_template

import updater
from memory import Memory
from tools import TOOLS as ANTHROPIC_TOOLS, run_tool

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
DEFAULT_MODEL = "qwen2.5:3b"

SYSTEM_PROMPT_TEMPLATE = """أنت وكيل شخصي ذكي ومستقل يعمل محليًا بالكامل على جهاز المستخدم،
ويتم التواصل معك عبر واجهة ويب احترافية بالمتصفح.

لديك ذاكرة طويلة المدى عن المستخدم، هذه المعلومات المحفوظة عنه حتى الآن:
{facts}

تعليمات:
- إذا لاحظت معلومة جديدة ومهمة عن المستخدم، استخدم أداة remember_fact لحفظها.
- استخدم run_python_code أو run_shell_command عند الحاجة لتنفيذ مهام فعلية.
- استخدم أداة web_search لأي سؤال عن معلومات حديثة أو أخبار أو أسعار.
- كن مباشرًا ومختصرًا، وتحدث بنفس لغة المستخدم.
"""

app = Flask(__name__)
memory = Memory()

# حالة أمر shell المعلّق بانتظار تأكيد المستخدم (تطبيق شخصي لمستخدم واحد)
pending = {"messages": None, "tool_calls": None, "index": None, "command": None}


def to_ollama_tools(anthropic_tools):
    converted = []
    for t in anthropic_tools:
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
        )
    return converted


OLLAMA_TOOLS = to_ollama_tools(ANTHROPIC_TOOLS)


def current_model() -> str:
    return memory.get_setting("model", DEFAULT_MODEL)


def confirm_shell_enabled() -> bool:
    return memory.get_setting("confirm_shell", True)


def build_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(facts=memory.get_facts_text())


def call_ollama(messages):
    response = requests.post(
        OLLAMA_CHAT_URL,
        json={"model": current_model(), "messages": messages, "tools": OLLAMA_TOOLS, "stream": False},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


def process_tool_calls(messages, tool_calls, start_index=0):
    """ينفذ الأدوات بدءًا من start_index. يوقف وينتظر تأكيد المستخدم لو
    صادف أمر shell وكان التأكيد مفعّل بالإعدادات."""
    for i in range(start_index, len(tool_calls)):
        call = tool_calls[i]
        fn = call.get("function", {})
        name = fn.get("name")
        args = fn.get("arguments", {})

        if name == "run_shell_command" and confirm_shell_enabled():
            pending.update(messages=messages, tool_calls=tool_calls, index=i, command=args.get("command", ""))
            return {"needs_confirmation": True, "command": pending["command"]}

        result = run_tool(name, args, memory=memory, confirm_shell=False)
        messages.append({"role": "tool", "content": result})

    return None


def continue_conversation(messages):
    while True:
        data = call_ollama(messages)
        message = data.get("message", {})
        assistant_text = (message.get("content") or "").strip()
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            if assistant_text:
                memory.add_message("assistant", assistant_text)
            return {"reply": assistant_text, "facts": memory.data["facts"]}

        messages.append({"role": "assistant", "content": assistant_text, "tool_calls": tool_calls})

        confirmation = process_tool_calls(messages, tool_calls, 0)
        if confirmation:
            return confirmation


# ---------- الصفحة الرئيسية ----------
@app.route("/")
def index():
    return render_template("index.html")


# ---------- الدردشة ----------
@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "الرسالة فارغة"}), 400

    memory.add_message("user", user_message)
    messages = [{"role": "system", "content": build_system_prompt()}]
    messages += memory.get_recent_messages(n=30)

    try:
        result = continue_conversation(messages)
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "تعذر الاتصال بـ Ollama. تأكد إنه يعمل بالأمر: ollama serve"}), 500
    except requests.exceptions.Timeout:
        return jsonify({"error": "انتهت مهلة الانتظار من Ollama. جرب مرة أخرى."}), 500
    except Exception as e:
        return jsonify({"error": f"خطأ غير متوقع: {e}"}), 500

    return jsonify(result)


@app.route("/api/confirm", methods=["POST"])
def confirm():
    data = request.get_json(force=True)
    approved = bool(data.get("approved"))

    if pending["messages"] is None:
        return jsonify({"error": "لا يوجد أمر بانتظار التأكيد"}), 400

    messages = pending["messages"]
    tool_calls = pending["tool_calls"]
    index = pending["index"]
    call = tool_calls[index]
    args = call.get("function", {}).get("arguments", {})

    result = run_tool("run_shell_command", args, memory=memory, confirm_shell=False) if approved \
        else "المستخدم رفض تنفيذ هذا الأمر."
    messages.append({"role": "tool", "content": result})

    pending.update(messages=None, tool_calls=None, index=None, command=None)

    confirmation = process_tool_calls(messages, tool_calls, index + 1)
    if confirmation:
        return jsonify(confirmation)

    try:
        result = continue_conversation(messages)
    except Exception as e:
        return jsonify({"error": f"خطأ غير متوقع: {e}"}), 500

    return jsonify(result)


# ---------- الجلسات ----------
@app.route("/api/sessions", methods=["GET"])
def get_sessions():
    return jsonify({"sessions": memory.list_sessions(), "active": memory.get_active_session_id()})


@app.route("/api/sessions", methods=["POST"])
def create_session():
    sid = memory.new_session()
    return jsonify({"id": sid})


@app.route("/api/sessions/<sid>", methods=["GET"])
def get_session(sid):
    memory.set_active_session(sid)
    return jsonify({"messages": memory.get_session_messages(sid)})


@app.route("/api/sessions/<sid>", methods=["DELETE"])
def delete_session(sid):
    ok = memory.delete_session(sid)
    return jsonify({"ok": ok, "active": memory.get_active_session_id()})


# ---------- الحقائق المحفوظة ----------
@app.route("/api/facts", methods=["GET"])
def get_facts():
    return jsonify({"facts": memory.data["facts"]})


@app.route("/api/facts/<int:index>", methods=["DELETE"])
def delete_fact(index):
    ok = memory.delete_fact(index)
    return jsonify({"ok": ok})


# ---------- الإعدادات ----------
@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify({
        "model": current_model(),
        "confirm_shell": confirm_shell_enabled(),
        "theme": memory.get_setting("theme", "dark"),
    })


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json(force=True)
    if "model" in data:
        memory.set_setting("model", data["model"])
    if "confirm_shell" in data:
        memory.set_setting("confirm_shell", bool(data["confirm_shell"]))
    if "theme" in data:
        memory.set_setting("theme", data["theme"])
    return jsonify({"ok": True})


@app.route("/api/models", methods=["GET"])
def get_models():
    try:
        r = requests.get(OLLAMA_TAGS_URL, timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        return jsonify({"models": models})
    except Exception as e:
        return jsonify({"models": [], "error": str(e)})


# ---------- التحديثات ----------
@app.route("/api/check_update", methods=["GET"])
def check_update():
    return jsonify(updater.check_for_update())


@app.route("/api/apply_update", methods=["POST"])
def apply_update():
    return jsonify(updater.apply_update())


if __name__ == "__main__":
    print("=" * 50)
    print(f"🤖 الوكيل الشخصي (نسخة احترافية) | النموذج: {current_model()}")
    print("افتح المتصفح على: http://localhost:5000")
    print("=" * 50)
    app.run(host="127.0.0.1", port=5000, debug=False)
