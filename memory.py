"""
memory.py
----------
نظام ذاكرة متكامل للوكيل الشخصي، يدعم:
  - "facts": معلومات ثابتة عن المستخدم (مشتركة بين كل الجلسات)
  - "sessions": جلسات محادثة متعددة، كل جلسة عندها عنوان وتاريخها الخاص
  - "settings": إعدادات محفوظة (النموذج المختار، تأكيد أوامر shell، إلخ)

كل شيء محفوظ في ملف JSON على القرص، فيبقى موجود بعد إغلاق البرنامج.
"""

import json
import os
import uuid
from datetime import datetime

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "memory_store.json")
MAX_HISTORY_MESSAGES = 60  # عدد الرسائل المحفوظة لكل جلسة


class Memory:
    def __init__(self, path: str = MEMORY_FILE):
        self.path = path
        self.data = self._load()
        self._ensure_structure()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _ensure_structure(self):
        """يتأكد إن كل الحقول موجودة، ويحوّل أي بيانات قديمة (نسخة سابقة
        بدون نظام جلسات) لجلسة واحدة تلقائيًا حتى لا نخسر بيانات المستخدم."""
        self.data.setdefault("facts", [])
        self.data.setdefault("settings", {})
        self.data.setdefault("sessions", {})
        self.data.setdefault("knowledge", [])

        # توافق مع النسخة القديمة (history مباشرة بدون sessions)
        old_history = self.data.pop("history", None)
        if old_history and not self.data["sessions"]:
            sid = self._new_session_id()
            self.data["sessions"][sid] = {
                "title": "محادثة سابقة",
                "created": datetime.now().isoformat(),
                "history": old_history,
            }
            self.data["active_session"] = sid

        if not self.data.get("sessions"):
            self.new_session()
        elif not self.data.get("active_session") or self.data["active_session"] not in self.data["sessions"]:
            self.data["active_session"] = next(iter(self.data["sessions"]))

        self.save()

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _new_session_id() -> str:
        return uuid.uuid4().hex[:8]

    # ---------- الحقائق (Facts) ----------
    def add_fact(self, fact: str):
        fact = fact.strip()
        if fact and fact not in self.data["facts"]:
            self.data["facts"].append(fact)
            self.save()

    def delete_fact(self, index: int) -> bool:
        try:
            self.data["facts"].pop(index)
            self.save()
            return True
        except IndexError:
            return False

    def get_facts_text(self) -> str:
        if not self.data["facts"]:
            return "لا توجد معلومات محفوظة عن المستخدم بعد."
        return "\n".join(f"- {f}" for f in self.data["facts"])

    # ---------- الجلسات (Sessions) ----------
    def new_session(self, title: str = None) -> str:
        sid = self._new_session_id()
        self.data["sessions"][sid] = {
            "title": title or "محادثة جديدة",
            "created": datetime.now().isoformat(),
            "history": [],
        }
        self.data["active_session"] = sid
        self.save()
        return sid

    def list_sessions(self) -> list:
        items = [
            {"id": sid, "title": s["title"], "created": s["created"]}
            for sid, s in self.data["sessions"].items()
        ]
        items.sort(key=lambda x: x["created"], reverse=True)
        return items

    def get_active_session_id(self) -> str:
        return self.data["active_session"]

    def set_active_session(self, sid: str) -> bool:
        if sid in self.data["sessions"]:
            self.data["active_session"] = sid
            self.save()
            return True
        return False

    def delete_session(self, sid: str) -> bool:
        if sid not in self.data["sessions"]:
            return False
        del self.data["sessions"][sid]
        if self.data.get("active_session") == sid:
            remaining = list(self.data["sessions"].keys())
            self.data["active_session"] = remaining[0] if remaining else self.new_session()
        self.save()
        return True

    def get_session_messages(self, sid: str) -> list:
        session = self.data["sessions"].get(sid)
        return session["history"] if session else []

    # ---------- المحادثة الحالية (Active session history) ----------
    def add_message(self, role: str, content: str):
        sid = self.data["active_session"]
        session = self.data["sessions"][sid]
        session["history"].append(
            {"role": role, "content": content, "time": datetime.now().isoformat()}
        )
        if len(session["history"]) > MAX_HISTORY_MESSAGES:
            session["history"] = session["history"][-MAX_HISTORY_MESSAGES:]
        # عنوان تلقائي للجلسة من أول رسالة مستخدم
        if session["title"] == "محادثة جديدة" and role == "user":
            title = content.strip().replace("\n", " ")
            session["title"] = title[:40] + ("…" if len(title) > 40 else "")
        self.save()

    def get_recent_messages(self, n: int = 30) -> list:
        sid = self.data["active_session"]
        history = self.data["sessions"][sid]["history"]
        recent = history[-n:]
        return [{"role": m["role"], "content": m["content"]} for m in recent]

    # ---------- الإعدادات (Settings) ----------
    def get_setting(self, key: str, default=None):
        return self.data.get("settings", {}).get(key, default)

    def set_setting(self, key: str, value):
        self.data.setdefault("settings", {})[key] = value
        self.save()

    # ---------- ذاكرة المعرفة (نتائج بحث سابقة، تُستخدم للتعلّم والتسريع) ----------
    def add_knowledge(self, query: str, summary: str):
        """يخزن نتيجة بحث عشان يستخدمها لاحقًا بدل ما يعيد البحث من الصفر —
        هذا هو 'التعلّم' الفعلي والقابل للقياس: كل بحث جديد يصير معرفة دائمة."""
        self.data.setdefault("knowledge", [])
        self.data["knowledge"].append({
            "query": query.strip().lower(),
            "summary": summary,
            "time": datetime.now().isoformat(),
        })
        if len(self.data["knowledge"]) > 300:
            self.data["knowledge"] = self.data["knowledge"][-300:]
        self.save()

    def find_cached_knowledge(self, query: str, max_age_hours: float = 6):
        """يرجع نتيجة محفوظة سابقًا لنفس السؤال تقريبًا لو كانت حديثة، بدل
        إعادة البحث بالإنترنت من جديد (أسرع بكثير + يقلل الحمل)."""
        q = query.strip().lower()
        now = datetime.now()
        for item in reversed(self.data.get("knowledge", [])):
            if item["query"] == q:
                try:
                    age_hours = (now - datetime.fromisoformat(item["time"])).total_seconds() / 3600
                except ValueError:
                    continue
                if age_hours <= max_age_hours:
                    return item["summary"]
        return None

    def knowledge_count(self) -> int:
        return len(self.data.get("knowledge", []))

    def clear(self):
        self.data = {"facts": [], "settings": {}, "sessions": {}, "knowledge": []}
        self.new_session()
