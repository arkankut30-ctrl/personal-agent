"""
tools.py
--------
الأدوات (Tools) اللي الوكيل يقدر يستخدمها لتنفيذ مهام فعلية.
كل أداة معرّفة بصيغة JSON Schema يفهمها Claude API (tool use)،
ولها دالة تنفيذ فعلية في run_tool().

تحذير أمني: أداة run_shell_command تنفذ أوامر حقيقية على جهازك.
استخدمها بحذر، وراجع كل أمر قبل الموافقة عليه إذا فعّلت وضع
التأكيد (CONFIRM_BEFORE_RUN في agent.py).
"""

import subprocess
import io
import contextlib

# ---------- تعريف الأدوات لـ Claude ----------
TOOLS = [
    {
        "name": "run_python_code",
        "description": (
            "ينفذ كود Python ويرجع ناتج الطباعة (print). "
            "استخدمها للحسابات، معالجة البيانات، أو أي منطق برمجي."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "كود Python للتنفيذ"}
            },
            "required": ["code"],
        },
    },
    {
        "name": "run_shell_command",
        "description": (
            "ينفذ أمر shell على جهاز المستخدم ويرجع الناتج. "
            "استخدمها لإدارة الملفات، تشغيل برامج، إلخ. كن حذرًا."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "أمر shell للتنفيذ"}
            },
            "required": ["command"],
        },
    },
    {
        "name": "remember_fact",
        "description": (
            "يحفظ معلومة مهمة عن المستخدم في الذاكرة طويلة المدى "
            "(مثل: تفضيلاته، اهتماماته، معلومات متكررة تفيد المحادثات القادمة)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "المعلومة المراد حفظها، بجملة واضحة ومختصرة"}
            },
            "required": ["fact"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "يبحث في الإنترنت (عبر DuckDuckGo، بدون مفتاح API) ويرجع أهم النتائج "
            "بعناوينها وروابطها وملخص قصير. استخدمها لأي سؤال عن معلومات حديثة، "
            "أخبار، أسعار، أو أي شيء قد يكون تغيّر بعد آخر تحديث لمعرفتك."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "نص البحث"},
                "max_results": {
                    "type": "integer",
                    "description": "عدد النتائج المطلوبة (افتراضي 5)",
                },
            },
            "required": ["query"],
        },
    },
]


def run_tool(name: str, tool_input: dict, memory=None, confirm_shell: bool = True) -> str:
    """ينفذ الأداة المطلوبة ويرجع النتيجة كنص."""

    if name == "run_python_code":
        code = tool_input.get("code", "")
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                exec(code, {"__builtins__": __builtins__})
            output = buffer.getvalue()
            return output if output else "(تم التنفيذ بدون مخرجات طباعة)"
        except Exception as e:
            return f"خطأ أثناء التنفيذ: {e}"

    elif name == "run_shell_command":
        command = tool_input.get("command", "")
        if confirm_shell:
            print(f"\n⚠️  الوكيل يريد تنفيذ أمر shell التالي:\n    {command}")
            answer = input("هل توافق على تنفيذه؟ (y/n): ").strip().lower()
            if answer != "y":
                return "المستخدم رفض تنفيذ هذا الأمر."
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            output = result.stdout + result.stderr
            return output if output else "(تم التنفيذ بدون مخرجات)"
        except Exception as e:
            return f"خطأ أثناء تنفيذ الأمر: {e}"

    elif name == "remember_fact":
        fact = tool_input.get("fact", "")
        if memory is not None:
            memory.add_fact(fact)
            return f"تم حفظ المعلومة: {fact}"
        return "تعذر الحفظ: لا توجد ذاكرة متصلة."

    elif name == "web_search":
        query = tool_input.get("query", "")
        max_results = tool_input.get("max_results", 5)
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = 5

        if not query:
            return "تعذر البحث: لم يتم تحديد نص للبحث."

        # تحقق أول من ذاكرة المعرفة المتراكمة (أسرع بكثير من إعادة البحث)
        if memory is not None:
            cached = memory.find_cached_knowledge(query)
            if cached:
                return "(من الذاكرة المحفوظة مسبقًا، بحث سابق حديث)\n" + cached

        try:
            from ddgs import DDGS  # الاسم الجديد للمكتبة
        except ImportError:
            try:
                from duckduckgo_search import DDGS  # اسم قديم، للتوافق
            except ImportError:
                return (
                    "مكتبة البحث غير مثبتة. ثبّتها بالأمر: pip install ddgs"
                )

        try:
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    title = r.get("title", "").strip()
                    body = r.get("body", "").strip()
                    href = r.get("href", "").strip()
                    results.append(f"- {title}\n  {body}\n  رابط: {href}")

            if not results:
                return "لم يتم العثور على أي نتائج لهذا البحث."

            summary = "\n\n".join(results)

            # احفظ النتيجة بذاكرة المعرفة عشان يستفيد منها لاحقًا (تعلّم متراكم)
            if memory is not None:
                memory.add_knowledge(query, summary)

            return summary
        except Exception as e:
            return f"خطأ أثناء البحث في الإنترنت: {e}"

    else:
        return f"أداة غير معروفة: {name}"
